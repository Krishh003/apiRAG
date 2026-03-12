"""
Ingestion Scheduler — orchestrates the full ingestion pipeline.

Runs:
  1. OpenAPI parser  (Twilio, SendGrid, Stripe, Google Maps)
  2. Playwright scraper (WhatsApp, Meta, Instagram)
  3. Structuring/enrichment via Gemini Flash
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
        platforms=None means scrape ALL platforms.
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
            # ── Step 1: OpenAPI sources (Twilio, SendGrid, Stripe, Maps) ─────
            openapi_platforms = None
            if platforms:
                openapi_platforms = [p for p in platforms
                                     if p in ("Twilio", "SendGrid", "Stripe", "Google Maps")]

            if not platforms or openapi_platforms:
                logger.info("Starting OpenAPI ingestion...")
                openapi_entries = self.openapi_parser.parse_all(openapi_platforms)

                # Enrich with Gemini (plain_explanation + relationships)
                logger.info(f"Enriching {len(openapi_entries)} OpenAPI entries with Gemini...")
                openapi_entries = self.structuring.enrich_openapi_entries_batch(openapi_entries)
                all_entries.extend(openapi_entries)
                counts["openapi"] = len(openapi_entries)
                logger.info(f"OpenAPI ingestion complete: {len(openapi_entries)} entries")

            # ── Step 2: Meta platforms (WhatsApp, Meta, Instagram) ──────────
            #   Meta's developer site blocks headless browsers entirely,
            #   so we load curated API definitions from a local JSON file.
            meta_platforms = {"WhatsApp", "Meta", "Instagram"}
            should_load_meta = not platforms or any(p in meta_platforms for p in platforms)

            if should_load_meta:
                logger.info("Loading Meta/WhatsApp/Instagram API definitions from JSON...")
                meta_entries = self._load_meta_definitions(platforms)
                all_entries.extend(meta_entries)
                counts["meta_json"] = len(meta_entries)
                logger.info(f"Meta JSON ingestion complete: {len(meta_entries)} entries")

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

    def _load_meta_definitions(self, platforms: Optional[List[str]] = None) -> List[APIEntry]:
        """
        Load WhatsApp/Meta/Instagram API definitions from a curated JSON file.
        Meta's developer docs block headless browsers entirely, so we maintain
        hand-curated definitions in ingestion/meta_api_definitions.json.
        """
        json_path = os.path.join(os.path.dirname(__file__), "meta_api_definitions.json")
        if not os.path.exists(json_path):
            logger.warning(f"Meta definitions file not found: {json_path}")
            return []

        with open(json_path, "r", encoding="utf-8") as f:
            raw_entries = json.load(f)

        # Map "category" field from JSON to "platform" for APIEntry
        meta_platform_map = {
            "WhatsApp": "WhatsApp",
            "Meta": "Meta",
            "Instagram": "Instagram",
        }

        entries = []
        for obj in raw_entries:
            # Determine the platform from the category field
            raw_category = obj.get("category", "")
            platform = meta_platform_map.get(raw_category, raw_category)

            # Filter by requested platforms if specified
            if platforms and platform not in platforms:
                continue

            entry = APIEntry(
                name=obj.get("name", "Unknown"),
                platform=platform,
                category=raw_category,
                method=obj.get("endpoint", "GET").split()[0] if obj.get("endpoint") else "GET",
                endpoint=obj.get("endpoint", ""),
                base_url=obj.get("base_url", "https://graph.facebook.com"),
                auth=obj.get("auth", "Bearer token"),
                description=obj.get("description", ""),
                plain_explanation=obj.get("plain_explanation", ""),
            )
            entries.append(entry)

        logger.info(f"Loaded {len(entries)} Meta API definitions from JSON")
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
