"""
Ingestion Scheduler — orchestrates the full ingestion pipeline.

Runs:
  1. OpenAPI parser  (Twilio, SendGrid, Stripe, Google Maps, WhatsApp)
  2. Curated JSON definitions (Meta/Instagram, GA4, Meta Ads,
     Meta Pixel/CAPI, Shopify, AppsFlyer, Firebase)
  3. Structuring/enrichment via Gemini Flash (OpenAPI entries only)
  4. Push to ChromaDB (vector store)
  5. Push to Neo4j (graph store)

Scheduling:
  - Automatic: configurable cron via APScheduler
  - Manual: callable directly via POST /admin/scrape endpoint
"""

import json
import logging
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from models import APIEntry
from ingestion.openapi_parser import OpenAPIParser
from ingestion.playwright_scraper import PlaywrightScraper
from ingestion.structuring import StructuringPipeline

logger = logging.getLogger(__name__)

# Shared state for job status
scrape_status: Dict[str, Any] = {
    "last_run": None,
    "last_status": "never_run",
    "last_counts": {},
    "is_running": False,
}

# All curated JSON definition files and the platforms they cover
JSON_DEFINITION_FILES = [
    {
        "filename": "meta_api_definitions.json",
        "platforms": {"Meta", "Instagram"},
        "default_base_url": "https://graph.facebook.com",
        "default_auth": "Bearer token",
        "default_version": "v23.0",
    },
    {
        "filename": "ga4_api_definitions.json",
        "platforms": {"GA4"},
        "default_base_url": "https://analyticsdata.googleapis.com",
        "default_auth": "OAuth 2.0 Service Account",
        "default_version": "v1beta",
    },
    {
        "filename": "meta_ads_api_definitions.json",
        "platforms": {"Meta Ads"},
        "default_base_url": "https://graph.facebook.com",
        "default_auth": "System User access token with ads_read permission",
        "default_version": "v23.0",
    },
    {
        "filename": "meta_pixel_capi_definitions.json",
        "platforms": {"Meta Pixel"},
        "default_base_url": "https://graph.facebook.com",
        "default_auth": "Meta Pixel ID / System User access token",
        "default_version": "v23.0",
    },
    {
        "filename": "shopify_api_definitions.json",
        "platforms": {"Shopify"},
        "default_base_url": "https://{store-name}.myshopify.com",
        "default_auth": "Admin API access token in X-Shopify-Access-Token header",
        "default_version": "2024-10",
    },
    {
        "filename": "appsflyer_api_definitions.json",
        "platforms": {"AppsFlyer"},
        "default_base_url": "https://hq1.appsflyer.com",
        "default_auth": "API V2 token in Authorization header",
        "default_version": "v5",
    },
    {
        "filename": "firebase_api_definitions.json",
        "platforms": {"Firebase"},
        "default_base_url": "https://firebase.google.com",
        "default_auth": "Firebase App credentials",
        "default_version": "SDK",
    },
]


class IngestionScheduler:

    def __init__(self, vector_store, graph_store, gemini_api_key: str):
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.structuring = StructuringPipeline(gemini_api_key)
        self.openapi_parser = OpenAPIParser()
        self.playwright_scraper = PlaywrightScraper()
        self._scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    # ── Core pipeline ─────────────────────────────────────────────────────

    def run_ingestion(self, platforms: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Full ingestion pipeline. Callable directly for manual runs.
        platforms=None means load ALL platforms.
        """
        global scrape_status
        if scrape_status["is_running"]:
            return {"error": "Ingestion already in progress. Please wait."}

        scrape_status["is_running"] = True
        scrape_status["last_run"] = datetime.now().isoformat()
        scrape_status["last_status"] = "running"

        all_entries: List[APIEntry] = []
        counts: Dict[str, int] = {}

        try:
            # ── Step 1: OpenAPI sources (Twilio, SendGrid, Stripe, Maps, WhatsApp) ──
            openapi_platforms = None
            if platforms:
                openapi_platforms = [p for p in platforms
                                     if p in ("Twilio", "SendGrid", "Stripe", "Google Maps", "WhatsApp")]

            if not platforms or openapi_platforms:
                logger.info("Starting OpenAPI ingestion...")
                openapi_entries = self.openapi_parser.parse_all(openapi_platforms)

                # Enrich with Gemini (plain_explanation + relationships)
                logger.info(f"Enriching {len(openapi_entries)} OpenAPI entries with Gemini...")
                openapi_entries = self.structuring.enrich_openapi_entries_batch(openapi_entries)
                all_entries.extend(openapi_entries)
                counts["openapi"] = len(openapi_entries)
                logger.info(f"OpenAPI ingestion complete: {len(openapi_entries)} entries")

            # ── Step 2: Curated JSON definition files ─────────────────────────
            #   Covers: Meta/Instagram, GA4, Meta Ads, Meta Pixel/CAPI,
            #           Shopify, AppsFlyer, Firebase
            for file_config in JSON_DEFINITION_FILES:
                file_platforms = file_config["platforms"]
                should_load = not platforms or any(p in file_platforms for p in platforms)

                if should_load:
                    entries = self._load_json_definitions(
                        filename=file_config["filename"],
                        platforms=platforms,
                        default_base_url=file_config["default_base_url"],
                        default_auth=file_config["default_auth"],
                        default_version=file_config["default_version"],
                    )
                    all_entries.extend(entries)
                    key = file_config["filename"].replace(".json", "")
                    counts[key] = len(entries)

            # ── Step 3: Push to ChromaDB ───────────────────────────────────────
            logger.info(f"Pushing {len(all_entries)} entries to ChromaDB...")
            self.vector_store.upsert_entries(all_entries)
            counts["pushed_to_vector"] = len(all_entries)

            # ── Step 4: Push to Neo4j ──────────────────────────────────────────
            logger.info(f"Pushing {len(all_entries)} entries to Neo4j...")
            self.graph_store.upsert_entries(all_entries)
            counts["pushed_to_graph"] = len(all_entries)

            scrape_status["last_status"] = "success"
            scrape_status["last_counts"] = counts
            logger.info(f"Full ingestion complete: {counts}")
            return {"status": "success", "counts": counts}

        except Exception as e:
            logger.exception(f"Ingestion pipeline failed: {e}")
            scrape_status["last_status"] = f"failed: {str(e)}"
            return {"status": "error", "error": str(e)}
        finally:
            scrape_status["is_running"] = False

    def ingest_internal_api(self, entry: APIEntry) -> bool:
        """
        Ingest a single internal API wrapper entry.
        Called from the manual entry endpoint in main.py.
        """
        try:
            entry.is_internal = True
            self.vector_store.upsert_entries([entry])
            self.graph_store.upsert_entries([entry])
            return True
        except Exception as e:
            logger.error(f"Failed to ingest internal API: {e}")
            return False

    def _load_json_definitions(
        self,
        filename: str,
        platforms: Optional[List[str]] = None,
        default_base_url: str = "",
        default_auth: str = "See documentation",
        default_version: str = "",
    ) -> List[APIEntry]:
        """
        Generic loader for curated API definition JSON files.

        Each JSON file is a list of objects with fields:
          name, category (used as platform), endpoint, description,
          plain_explanation, base_url (optional), auth (optional),
          doc_url (optional)

        The 'category' field in the JSON determines both the platform and
        category fields on the resulting APIEntry.
        """
        json_path = os.path.join(os.path.dirname(__file__), filename)
        if not os.path.exists(json_path):
            logger.warning(f"Definitions file not found: {json_path}")
            return []

        with open(json_path, "r", encoding="utf-8") as f:
            raw_entries = json.load(f)

        entries = []
        for obj in raw_entries:
            raw_category = obj.get("category", "")
            platform = raw_category  # category IS the platform for curated JSON files

            # Filter by requested platforms if specified
            if platforms and platform not in platforms:
                continue

            # Parse method from endpoint string (e.g. "POST /v1/..." → "POST", "/v1/...")
            endpoint_str = obj.get("endpoint", "")
            parts = endpoint_str.split(None, 1)
            if len(parts) == 2 and parts[0].upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                method = parts[0].upper()
                endpoint_path = parts[1]
            else:
                method = "GET"
                endpoint_path = endpoint_str

            entry = APIEntry(
                name=obj.get("name", "Unknown"),
                platform=platform,
                category=raw_category,
                version=obj.get("version", default_version),
                method=method,
                endpoint=endpoint_path,
                base_url=obj.get("base_url", default_base_url),
                auth=obj.get("auth", default_auth),
                description=obj.get("description", ""),
                plain_explanation=obj.get("plain_explanation", ""),
                doc_url=obj.get("doc_url", ""),
            )
            entries.append(entry)

        logger.info(f"Loaded {len(entries)} entries from {filename}")
        return entries

    def run_single_url_ingestion(self, url: str, platform: str, category: str) -> Dict[str, Any]:
        """Scrape and ingest a single URL."""
        logger.info(f"Starting single-URL ingestion for: {url}")
        try:
            raw_blocks = self.playwright_scraper.scrape_url(url, platform, category)
            if not raw_blocks:
                logger.warning(f"No content found for URL: {url}")
                return {"status": "error", "error": "No content found on the provided page."}

            logger.info(f"Structuring {len(raw_blocks)} raw blocks with Gemini...")
            entries = self.structuring.structure_raw_blocks_batch(raw_blocks)

            if not entries:
                 logger.warning(f"Gemini failed to structure blocks from: {url}")
                 return {"status": "error", "error": "Could not identify any API endpoints on this page."}

            logger.info(f"Pushing {len(entries)} entries to stores...")
            self.vector_store.upsert_entries(entries)
            self.graph_store.upsert_entries(entries)

            logger.info(f"Single-URL ingestion complete for {url}")
            return {"status": "success", "count": len(entries), "names": [e.name for e in entries]}

        except Exception as e:
            logger.exception(f"Single-URL ingestion failed: {e}")
            return {"status": "error", "error": str(e)}

    # ── Scheduler setup ───────────────────────────────────────────────────

    def start_scheduler(self):
        """Start APScheduler with cron from env vars."""
        day = os.getenv("SCRAPE_CRON_DAY", "sun")
        hour = int(os.getenv("SCRAPE_CRON_HOUR", "2"))

        self._scheduler.add_job(
            func=self.run_ingestion,
            trigger=CronTrigger(day_of_week=day, hour=hour, minute=0),
            id="full_ingestion",
            name="Weekly full ingestion",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(f"Scheduler started: runs every {day} at {hour:02d}:00 IST")

    def stop_scheduler(self):
        if self._scheduler.running:
            self._scheduler.shutdown()

    def get_next_run(self) -> Optional[str]:
        job = self._scheduler.get_job("full_ingestion")
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
        return None
