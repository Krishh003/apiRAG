"""
API Knowledge Base RAG — v2
FastAPI backend with all routes.
"""

import os
import logging
import csv
import io
import json
import re
from contextlib import asynccontextmanager
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import pypdf

os.environ["ANONYMIZED_TELEMETRY"] = "False"

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

# ── Singletons (initialized at startup) ─────────────────────────────────────
vector_store = None
graph_store = None
reranker = None
classifier = None
lookup_handler = None
planning_handler = None
advisory_handler = None
comparison_handler = None
scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize all components on startup."""
    global vector_store, graph_store, reranker, classifier
    global lookup_handler, planning_handler, advisory_handler, comparison_handler, scheduler

    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        raise RuntimeError("GEMINI_API_KEY not set in .env")

    logger.info("Initializing vector store...")
    from retrieval.vector_store import VectorStore
    vector_store = VectorStore(chroma_path=os.getenv("CHROMA_PATH", "./chroma_db"))

    logger.info("Initializing graph store...")
    from retrieval.graph_store import GraphStore
    graph_store = GraphStore(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "changeme"),
    )

    logger.info("Initializing reranker...")
    from retrieval.reranker import Reranker
    reranker = Reranker()

    logger.info("Initializing query classifier...")
    from query.classifier import QueryClassifier
    classifier = QueryClassifier(gemini_key)

    logger.info("Initializing lookup handler...")
    from query.lookup_handler import LookupHandler
    lookup_handler = LookupHandler(vector_store, reranker, gemini_key)

    logger.info("Initializing planning handler...")
    from query.planning_handler import PlanningHandler
    planning_handler = PlanningHandler(vector_store, graph_store, reranker, gemini_key)

    logger.info("Initializing advisory handler...")
    from query.advisory_handler import AdvisoryHandler
    advisory_handler = AdvisoryHandler(vector_store, reranker, gemini_key)

    logger.info("Initializing comparison handler...")
    from query.comparison_handler import ComparisonHandler
    comparison_handler = ComparisonHandler(vector_store, reranker, gemini_key)

    logger.info("Initializing ingestion scheduler...")
    from ingestion.scheduler import IngestionScheduler
    scheduler = IngestionScheduler(vector_store, graph_store, gemini_key)
    scheduler.start_scheduler()

    logger.info("All systems ready.")
    yield

    # Shutdown
    if scheduler:
        scheduler.stop_scheduler()
    if graph_store:
        graph_store.close()
    logger.info("Shutdown complete.")


app = FastAPI(title="API Knowledge Base RAG v2", lifespan=lifespan)


# ── Pydantic request/response models ─────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str
    platform_filter: Optional[str] = None
    category_filter: Optional[str] = None


class ManualAPIEntry(BaseModel):
    name: str
    platform: str
    category: str
    version: str = ""
    method: str = "GET"
    endpoint: str
    base_url: str = ""
    auth: str = ""
    description: str
    plain_explanation: str
    is_internal: bool = False
    internal_notes: str = ""


class ScrapeRequest(BaseModel):
    platforms: Optional[List[str]] = None


class ScrapeUrlRequest(BaseModel):
    url: str
    platform: str = "Imported"
    category: str = "General"


# ── Query routes ──────────────────────────────────────────────────────────────

@app.post("/api/query")
async def query(req: QueryRequest):
    """Main query endpoint. Auto-routes to lookup or planning handler."""
    if vector_store.count() == 0:
        return {
            "answer": "The knowledge base is empty. Please run the scraper first via POST /admin/scrape, or add APIs manually.",
            "query_type": "lookup",
            "sources": [],
            "plan_steps": [],
        }

    query_type, method = classifier.classify(req.question)
    logger.info(f"Query classified as '{query_type}' via {method}: {req.question[:80]}")

    if query_type == "planning":
        result = planning_handler.handle(
            req.question,
            platform_filter=req.platform_filter,
            category_filter=req.category_filter,
        )
    elif query_type == "advisory":
        result = advisory_handler.handle(
            req.question,
            platform_filter=req.platform_filter,
            category_filter=req.category_filter,
        )
    elif query_type == "comparison":
        result = comparison_handler.handle(
            req.question,
            platform_filter=req.platform_filter,
            category_filter=req.category_filter,
        )
    else:
        result = lookup_handler.handle(
            req.question,
            platform_filter=req.platform_filter,
            category_filter=req.category_filter,
        )

    return {
        "answer": result.answer,
        "query_type": result.query_type,
        "sources": result.sources,
        "plan_steps": result.plan_steps,
        "confidence": result.confidence,
        "confidence_label": result.confidence_label,
    }


# ── API entry management ──────────────────────────────────────────────────────

@app.post("/api/apis")
async def add_api(entry: ManualAPIEntry):
    """Manually add a single API entry (for internal APIs or custom entries)."""
    from models import APIEntry
    api_entry = APIEntry(
        name=entry.name,
        platform=entry.platform,
        category=entry.category,
        version=entry.version,
        method=entry.method,
        endpoint=entry.endpoint,
        base_url=entry.base_url,
        auth=entry.auth,
        description=entry.description,
        plain_explanation=entry.plain_explanation,
        is_internal=entry.is_internal,
        internal_notes=entry.internal_notes,
    )
    scheduler.ingest_internal_api(api_entry)
    return {"message": f"'{entry.name}' added successfully."}


@app.get("/api/apis")
async def list_apis(platform: Optional[str] = None):
    """List all stored APIs, optionally filtered by platform."""
    all_apis = vector_store.list_all()
    if platform:
        all_apis = [a for a in all_apis if a.get("platform") == platform]
    return all_apis


@app.delete("/api/apis/{api_id}")
async def delete_api(api_id: str):
    vector_store.delete_entry(api_id)
    return {"message": "Deleted."}


@app.get("/api/platforms")
async def get_platforms():
    return vector_store.get_platforms()


@app.get("/api/categories")
async def get_categories(platform: Optional[str] = None):
    return vector_store.get_categories(platform)


# ── File upload ───────────────────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Bulk import from .json, .csv, .txt, or .pdf file."""
    from models import APIEntry
    content = await file.read()
    filename = file.filename.lower()
    added, errors = [], []

    def push_entry(obj: dict):
        entry = APIEntry(
            name=obj.get("name", "Unknown"),
            platform=obj.get("platform", obj.get("category", "Uncategorized")),
            category=obj.get("category", "General"),
            version=obj.get("version", ""),
            method=obj.get("method", "GET"),
            endpoint=obj.get("endpoint", ""),
            base_url=obj.get("base_url", ""),
            auth=obj.get("auth", ""),
            description=obj.get("description", ""),
            plain_explanation=obj.get("plain_explanation", obj.get("plain", "")),
            is_internal=bool(obj.get("is_internal", False)),
        )
        scheduler.ingest_internal_api(entry)
        return entry.name

    if filename.endswith(".json"):
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                data = [data]
            for i, obj in enumerate(data):
                try:
                    added.append(push_entry(obj))
                except Exception as e:
                    errors.append(f"Row {i}: {e}")
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"Invalid JSON: {e}")

    elif filename.endswith(".csv"):
        for i, row in enumerate(csv.DictReader(io.StringIO(content.decode("utf-8", errors="replace")))):
            try:
                added.append(push_entry(dict(row)))
            except Exception as e:
                errors.append(f"Row {i}: {e}")

    elif filename.endswith(".txt"):
        for i, block in enumerate(re.split(r"\n\s*\n", content.decode("utf-8", errors="replace").strip())):
            if not block.strip():
                continue
            kv = {}
            for line in block.strip().splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    kv[k.strip().lower().replace(" ", "_")] = v.strip()
            try:
                added.append(push_entry(kv))
            except Exception as e:
                errors.append(f"Block {i}: {e}")

    elif filename.endswith(".pdf"):
        for i, page in enumerate(pypdf.PdfReader(io.BytesIO(content)).pages):
            text = (page.extract_text() or "").strip()
            if text:
                try:
                    added.append(push_entry({
                        "name": f"PDF Page {i+1} — {file.filename}",
                        "platform": "Imported",
                        "category": "PDF Import",
                        "description": text,
                        "plain_explanation": text,
                    }))
                except Exception as e:
                    errors.append(f"Page {i}: {e}")

    elif filename.endswith(".md"):
        text = content.decode("utf-8", errors="replace").strip()
        # Split by headers (H1, H2, H3)
        sections = re.split(r"\n(?=#+\s+)", "\n" + text)
        for i, section in enumerate(sections):
            section = section.strip()
            if not section:
                continue
            
            lines = section.splitlines()
            # If the first line is a header, use it as the name
            if lines[0].startswith("#"):
                name = lines[0].lstrip("#").strip()
            else:
                name = f"Markdown Section {i+1} — {file.filename}"
            
            try:
                added.append(push_entry({
                    "name": name,
                    "platform": "Imported",
                    "category": "Markdown Import",
                    "description": section,
                    "plain_explanation": section,
                }))
            except Exception as e:
                errors.append(f"Section {i}: {e}")
    else:
        raise HTTPException(400, "Unsupported file type. Use .json, .csv, .txt, .pdf, or .md")

    return {"added": added, "errors": errors, "count": len(added)}


# ── Admin — Scraping ──────────────────────────────────────────────────────────

@app.post("/admin/scrape")
async def trigger_scrape(req: ScrapeRequest, background_tasks: BackgroundTasks):
    """
    Manually trigger the full ingestion pipeline.
    Runs in background — returns immediately with a job started message.
    platforms: null = scrape all, or list like ["WhatsApp", "Stripe"]
    """
    from ingestion.scheduler import scrape_status
    if scrape_status["is_running"]:
        return {"message": "Scrape already in progress.", "status": "running"}

    background_tasks.add_task(scheduler.run_ingestion, req.platforms)
    return {
        "message": "Scrape started in background.",
        "platforms": req.platforms or "all",
        "status": "started",
    }


@app.post("/admin/scrape/url")
async def scrape_single_url(req: ScrapeUrlRequest, background_tasks: BackgroundTasks):
    """
    Scrape a single URL and ingest any API documentation found.
    Designed for non-technical users — just give it a website URL.
    Runs synchronously because single-page scrapes are fast (~30s).
    """
    import asyncio

    # Run in a thread to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        scheduler.run_single_url_ingestion,
        req.url, req.platform, req.category,
    )

    if result.get("status") == "success":
        # Reload API list counts
        return {
            "message": f"Found and added {result['count']} API(s) from that page.",
            "status": "success",
            "count": result["count"],
            "names": result.get("names", []),
        }
    else:
        return {
            "message": result.get("error", "Failed to scrape that URL."),
            "status": "error",
        }


@app.get("/admin/scrape/status")
async def scrape_status_endpoint():
    """Check the status of the last scrape run."""
    from ingestion.scheduler import scrape_status
    return {
        **scrape_status,
        "total_apis_stored": vector_store.count(),
        "next_scheduled_run": scheduler.get_next_run(),
    }


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    neo4j_ok = graph_store.health_check()
    return {
        "status": "ok",
        "vector_store_count": vector_store.count(),
        "neo4j": "connected" if neo4j_ok else "disconnected",
        "platforms": vector_store.get_platforms(),
    }


# ── Frontend ──────────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def serve_frontend():
    return FileResponse("static/index.html")
