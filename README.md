# API Knowledge Base RAG v2

An internal Retrieval-Augmented Generation system that lets non-technical employees ask plain-English questions about company APIs and receive documentation-based answers and plans.

Built with FastAPI, ChromaDB, Neo4j, and Google Gemini.

---

## Overview

Non-technical team members (marketers, managers, analysts) need to understand what APIs do, how to combine them into workflows, and how to reason about data discrepancies across platforms. This system provides a single chat interface where they can ask questions in plain English and get answers grounded in actual API documentation.

The system auto-classifies every question into one of four modes and routes it to a specialized handler:

| Mode | Example Question | LLM | Strategy |
| --- | --- | --- | --- |
| **Lookup** | "What does the WhatsApp Send Message API do?" | Gemini Flash | Hybrid search + rerank |
| **Planning** | "How do I charge a customer for their order?" | Gemini Pro | Graph traversal + hybrid search |
| **Advisory** | "Why do Shopify numbers differ from GA4?" | Gemini Pro | KB context + general knowledge |
| **Comparison** | "Difference between capturing and confirming a PaymentIntent?" | Gemini Flash | Per-concept retrieval + rerank |

---

## Features

- **Four query modes** with automatic classification (advisory > comparison > planning > lookup)
- **Hybrid search** combining vector similarity (bge-large-en-v1.5) and BM25 keyword matching via Reciprocal Rank Fusion
- **Cross-encoder reranking** (ms-marco-MiniLM-L-6-v2) for source selection
- **Neo4j graph traversal** for multi-hop API workflow planning
- **12 platforms** indexed: Twilio, SendGrid, Stripe, Google Maps, WhatsApp, Meta Graph, Instagram, GA4, Meta Ads, Meta Pixel/CAPI, Shopify, AppsFlyer, Firebase
- **Multiple ingestion methods**: OpenAPI spec parsing, curated JSON definitions, Playwright scraping, file upload (.json, .csv, .txt, .pdf, .md), manual entry
- **Scheduled ingestion** via APScheduler (weekly cron)
- **Responsive frontend** with dark/light themes, mode selector, platform filters, and drag-and-drop file upload

---

## Tech Stack

| Component | Technology |
|---|---|
| Backend | FastAPI 0.115.5 (Python) |
| LLM | Google Gemini 2.5 Flash + Pro |
| Vector DB | ChromaDB 0.5.23 (persistent, local) |
| Embeddings | BAAI/bge-large-en-v1.5 |
| Keyword Search | rank_bm25 (Reciprocal Rank Fusion) |
| Reranker | cross-encoder/ms-marco-MiniLM-L-6-v2 |
| Graph DB | Neo4j 5.26 Community (Docker) |
| Scraper | Playwright 1.49.0 (subprocess-isolated) |
| Scheduler | APScheduler 3.10.4 |
| Frontend | Vanilla HTML/CSS/JS (single-page) |

---

## Quick Start

### Prerequisites

- Python 3.10+
- Docker (for Neo4j)
- A [Google AI Studio](https://aistudio.google.com) API key (Gemini)

### 1. Clone and configure

```bash
git clone <repo-url>
cd apiRAG
cp .env.example .env
```

Edit `.env` with your credentials:
```
GEMINI_API_KEY=your_gemini_key
NEO4J_PASSWORD=your_neo4j_password
```

### 2. Start Neo4j

```bash
docker-compose up -d
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Start the server

```bash
uvicorn main:app --reload --port 8000
```

### 5. Populate the knowledge base

Use the UI (click **Run Scraper** in the sidebar) or the API:

```powershell
# PowerShell (Windows)
Invoke-RestMethod -Uri "http://localhost:8000/admin/scrape" -Method POST -ContentType "application/json" -Body '{}'
```

```bash
# bash / curl (Linux/macOS)
curl -X POST http://localhost:8000/admin/scrape -H "Content-Type: application/json" -d '{}'
```

### 6. Open the UI

Navigate to [http://localhost:8000](http://localhost:8000).

Interactive API docs are available at [http://localhost:8000/docs](http://localhost:8000/docs).

---

## Project Structure

```
apiRAG/
├── main.py                             # FastAPI app, all routes, lifespan startup
├── models.py                           # APIEntry schema + request/response models
├── requirements.txt                    # Python dependencies
├── docker-compose.yml                  # Neo4j container
├── .env.example                        # Environment variable template
├── CONTRIBUTING.md                     # Contribution guidelines
├── CHANGELOG.md                        # Version history
├── HANDOVER.md                         # Developer handover notes
├── internal_api_template.json          # Template for internal API wrappers
│
├── query/                              # Query classification and handling
│   ├── classifier.py                   #   4-way classifier (heuristic + Gemini)
│   ├── lookup_handler.py               #   Hybrid search -> rerank -> Gemini Flash
│   ├── planning_handler.py             #   Graph + hybrid search -> rerank -> Gemini Pro
│   ├── advisory_handler.py             #   Hybrid search -> rerank -> Gemini Pro
│   └── comparison_handler.py           #   Per-concept search -> rerank -> Gemini Flash
│
├── retrieval/                          # Search and ranking
│   ├── vector_store.py                 #   ChromaDB + BM25 + RRF hybrid search
│   ├── graph_store.py                  #   Neo4j CRUD + relationship traversal
│   └── reranker.py                     #   Cross-encoder reranking
│
├── ingestion/                          # Data pipeline
│   ├── scheduler.py                    #   Pipeline orchestration + cron scheduling
│   ├── openapi_parser.py               #   GitHub OpenAPI spec parsing
│   ├── playwright_scraper.py           #   Headless browser scraping (non-Meta)
│   ├── structuring.py                  #   Gemini Flash normalization to APIEntry
│   ├── meta_api_definitions.json       #   Curated: Meta Graph (9) + Instagram (4)
│   ├── ga4_api_definitions.json        #   Curated: GA4 Data + Admin API (9)
│   ├── meta_ads_api_definitions.json   #   Curated: Meta Ads / Marketing API (8)
│   ├── meta_pixel_capi_definitions.json#   Curated: Meta Pixel + CAPI (7)
│   ├── shopify_api_definitions.json    #   Curated: Shopify Admin API (9)
│   ├── appsflyer_api_definitions.json  #   Curated: AppsFlyer Pull API (6)
│   └── firebase_api_definitions.json   #   Curated: Firebase Analytics (6)
│
├── static/                             # Frontend
│   ├── index.html                      #   Main UI
│   ├── style.css                       #   Styles (light/dark themes)
│   └── app.js                          #   Client-side logic
│
├── chroma_db/                          # ChromaDB persistent storage (gitignored)
│
└── docs/                               # Extended documentation
    ├── architecture.md                 #   System design and data flow
    ├── query-modes.md                  #   Detailed query mode documentation
    ├── ingestion.md                    #   How to add platforms and data
    ├── api-reference.md                #   Full endpoint reference with schemas
    ├── configuration.md                #   Environment variables and config
    ├── deployment.md                   #   Production deployment guide
    └── troubleshooting.md              #   Common issues and solutions
```

---

## API Endpoints

| Method | Route | Description |
|---|---|---|
| `POST` | `/api/query` | Ask a question (auto-routes to appropriate handler) |
| `GET` | `/api/apis` | List all stored API entries |
| `POST` | `/api/apis` | Add a single API manually |
| `DELETE` | `/api/apis/{id}` | Delete an API entry |
| `GET` | `/api/platforms` | List all platform names |
| `GET` | `/api/categories` | List all category names |
| `POST` | `/api/upload` | Bulk import from file (.json, .csv, .txt, .pdf, .md) |
| `POST` | `/admin/scrape` | Trigger ingestion pipeline |
| `POST` | `/admin/scrape/url` | Scrape a single URL via Playwright |
| `GET` | `/admin/scrape/status` | Check scrape job status |
| `GET` | `/health` | System health check |
| `GET` | `/docs` | Interactive Swagger UI |

For full request/response schemas, see [docs/api-reference.md](docs/api-reference.md).

---

## Architecture

```
User Question
      |
      v
  Classifier (heuristic -> Gemini Flash fallback)
      |
      +---> Lookup -----> Hybrid Search -> Rerank -> Gemini Flash -> Answer
      |
      +---> Planning ---> Graph Traversal + Hybrid Search -> Rerank -> Gemini Pro -> Step-by-step Plan
      |
      +---> Advisory ---> Hybrid Search -> Rerank -> Gemini Pro (expert persona) -> Advice
      |
      +---> Comparison -> Per-concept Search -> Per-concept Rerank -> Gemini Flash -> Side-by-side
```

```
Ingestion Sources
      |
      +---> OpenAPI Specs (GitHub) -------> openapi_parser -> Gemini enrichment --+
      |                                                                           |
      +---> Curated JSON Definitions -----> scheduler._load_json_definitions() ---+--> ChromaDB + Neo4j
      |                                                                           |
      +---> Playwright Scraping ----------> structuring (Gemini Flash) -----------+
      |                                                                           |
      +---> Manual Entry / File Upload -------------------------------------------+
```

For a detailed architecture breakdown, see [docs/architecture.md](docs/architecture.md).

---

## Documentation

| Document | Description |
| --- | --- |
| [Architecture](docs/architecture.md) | System design, data flow, and design decisions |
| [Query Modes](docs/query-modes.md) | How each of the four query modes works |
| [Ingestion Guide](docs/ingestion.md) | How to add new platforms and data sources |
| [API Reference](docs/api-reference.md) | Full endpoint documentation with request/response schemas |
| [Configuration](docs/configuration.md) | All environment variables and configuration options |
| [Deployment](docs/deployment.md) | Production deployment with Docker |
| [Troubleshooting](docs/troubleshooting.md) | Common issues and solutions |
| [Contributing](CONTRIBUTING.md) | How to contribute to this project |
| [Changelog](CHANGELOG.md) | Version history |
| [Handover](HANDOVER.md) | Developer context and pending work |

## Evaluation and benchmarks

The [evaluation report](docs/evaluation/README.md) documents the repository audit,
100-question synthetic dataset, annotation schema, reusable retrieval ablations,
performance instrumentation and optional Gemini/human-review workflow.

The completed offline run uses 25 fictional endpoint documents and three passes
over 100 questions (1,200 predictions, zero retrieval errors). Ranking metrics
cover 87 answerable questions; 13 unanswerable/ambiguous items are excluded.

| Configuration | Recall@5 | MRR@10 |
|---|---:|---:|
| Dense BGE | 1.0000 | 0.9713 |
| BM25 | 0.9531 | 0.7541 |
| Dense + BM25/RRF | 1.0000 | 0.8860 |
| Hybrid + cross-encoder | 1.0000 | 0.9636 |

On this fixture, adding BM25/RRF lowered MRR@10 versus dense by 0.0852
(paired 95% bootstrap CI: -0.1360 to -0.0393). Reranking improved the hybrid
baseline by 0.0776 (CI: +0.0268 to +0.1312), without exceeding dense's observed
score. [Saved predictions, full metrics, confidence intervals and plots](docs/evaluation/results.md)
support these findings; they do not measure generated-answer correctness or
establish production-wide superiority.

A [BM25 Gemini diagnostic](docs/evaluation/answer-results.md)
produced seven answer texts from 12 questions; five hit quota-related application
failures. Human quality review, graph and healthy-service HTTP performance remain
incomplete. Existing architecture descriptions
are implementation descriptions, not evidence of measured superiority.

```powershell
python -m pip install numpy==2.2.6 rank_bm25==0.2.2
$env:PYTHONHASHSEED = '0'
python -m evaluation.run --bm25-only --output evaluation/runs/bm25-01 --repeats 3
python -m evaluation.run --score-only docs/evaluation/results/learned-03/predictions.jsonl --output evaluation/runs/rescore
```

See the report for full dependency setup, tests, learned-control commands,
performance controls, limitations and provenance review. Production
code and UI are unchanged by the evaluation suite.
