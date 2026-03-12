# HANDOVER — API Knowledge Base RAG v2

## For the next AI agent picking up this project

---

## Project Summary

An internal RAG (Retrieval-Augmented Generation) system that lets non-technical employees
ask plain-English questions about the APIs their company uses and get accurate answers.

Two query modes:

- Lookup — "What does the WhatsApp Send Message API do?" → plain English explanation
- Planning — "How do I charge a customer?" → step-by-step API call plan with parameters

Target users: non-technical team members who need to understand what APIs do and how to use them.
Deployed on: internal company server (Docker available). Currently being tested on developer's local Windows machine.

---

## Current State (as of 2026-03-12)

### What is working

- FastAPI backend starts and runs correctly
- ChromaDB vector store initialises with bge-large-en-v1.5 embeddings
- Neo4j graph store connects via Docker (bolt://localhost:7687)
- BM25 hybrid search + Reciprocal Rank Fusion implemented
- Cross-encoder reranker implemented
- Query classifier (lookup vs planning vs advisory) working — three-way classification
- Lookup handler working (Gemini 2.5 Flash, max_output_tokens: 1500, context: 1500 chars/source)
- Planning handler working (Gemini 2.5 Pro + graph traversal)
- Advisory handler working (Gemini 2.5 Pro, data engineering expert system prompt, KB context as grounding)
- OpenAPI ingestion pipeline working — Twilio, SendGrid, Stripe, Google Maps parse correctly from GitHub specs
- Meta/WhatsApp/Instagram ingestion working — loaded from curated JSON definitions (16 entries)
- GA4, Meta Ads, Meta Pixel/CAPI, Shopify, AppsFlyer, Firebase — curated JSON definitions added
- Manual API entry via POST /api/apis working
- File upload (.json, .csv, .txt, .pdf) working
- Single-URL scraping via "From Website" modal (Playwright, improved selectors)
- APScheduler weekly scrape cron running
- Frontend UI running at localhost:8000 — all emojis replaced with SVGs, advisory badge added

### What is NOT working / in progress

**Internal API wrappers** — user confirmed they have internal API wrappers but details are
not yet finalised. A template file internal_api_template.json exists for when they are ready.

**Playwright scraper does not work on Meta's developer docs** — Meta blocks all headless
browsers at the network level (connection times out). This was resolved by switching Meta
platforms to a curated JSON file (ingestion/meta_api_definitions.json). The Playwright
scraper still works for non-Meta URLs via the "From Website" single-URL feature.

---

## Tech Stack

| Component | Technology | Detail |
|---|---|---|
| Backend | FastAPI 0.115.5 | Python |
| LLM — lookup + classification | Gemini 2.5 Flash | model string: gemini-2.5-flash |
| LLM — planning queries | Gemini 2.5 Pro | model string: gemini-2.5-pro |
| LLM — advisory queries | Gemini 2.5 Pro | model string: gemini-2.5-pro |
| LLM — structuring + enrichment | Gemini 2.5 Flash | model string: gemini-2.5-flash |
| Vector DB | ChromaDB 0.5.23 | persistent, local |
| Embeddings | BAAI/bge-large-en-v1.5 | via sentence-transformers 2.7.0 |
| Keyword search | rank_bm25 0.2.2 | in-memory, rebuilt on upsert |
| Reranker | cross-encoder/ms-marco-MiniLM-L-6-v2 | lazy loaded on first use |
| Graph DB | Neo4j 5.26 Community | via Docker |
| Neo4j driver | neo4j 5.27.0 | bolt protocol |
| Scraper | Playwright 1.49.0 | sync API, isolated subprocess, non-Meta URLs only |
| HTML parsing | BeautifulSoup4 + lxml | 4.12.3 / 5.3.0 |
| Scheduler | APScheduler 3.10.4 | BackgroundScheduler, cron trigger |
| HTTP client | httpx 0.28.0 | fetching OpenAPI specs from GitHub |
| PDF parsing | pypdf 5.1.0 | file upload support |

### API Keys

- GEMINI_API_KEY — Google AI Studio (aistudio.google.com) — free tier available
- Do NOT use Claude/Anthropic APIs or OpenAI APIs anywhere in this codebase. The developer only has a Gemini key.

---

## Project Structure

```
api-rag-v2/
├── main.py                        # FastAPI app — all routes, lifespan startup/shutdown
├── models.py                      # Unified APIEntry schema + all request/response models
├── requirements.txt
├── docker-compose.yml             # Neo4j container
├── .env                           # API keys and config (never commit this)
├── .env.example                   # Template
├── internal_api_template.json     # Template for internal API wrapper entries
│
├── ingestion/
│   ├── openapi_parser.py              # Fetches and parses OpenAPI specs from GitHub
│   ├── playwright_scraper.py          # Scrapes non-Meta URLs via Playwright subprocess
│   ├── meta_api_definitions.json      # Curated WhatsApp/Meta/Instagram definitions (16 entries)
│   ├── ga4_api_definitions.json       # Curated GA4 Data API + Admin API definitions
│   ├── meta_ads_api_definitions.json  # Curated Meta Ads / Marketing API definitions
│   ├── meta_pixel_capi_definitions.json # Curated Meta Pixel + Conversions API definitions
│   ├── shopify_api_definitions.json   # Curated Shopify Admin API definitions
│   ├── appsflyer_api_definitions.json # Curated AppsFlyer Pull API definitions
│   ├── firebase_api_definitions.json  # Curated Firebase Analytics definitions
│   ├── structuring.py                 # Gemini Flash normalizes raw text to APIEntry schema
│   └── scheduler.py                   # Orchestrates full pipeline + APScheduler cron
│
├── retrieval/
│   ├── vector_store.py            # ChromaDB + bge-large + BM25 + RRF hybrid search
│   ├── graph_store.py             # Neo4j — CRUD + traversal queries
│   └── reranker.py                # Cross-encoder reranker
│
├── query/
│   ├── classifier.py              # Keyword heuristic + Gemini Flash → "lookup", "planning", or "advisory"
│   ├── lookup_handler.py          # Hybrid search → rerank → Gemini Flash (1500 token output)
│   ├── planning_handler.py        # Keywords → graph traversal → hybrid search → rerank → Gemini Pro
│   └── advisory_handler.py        # Hybrid search → rerank → Gemini Pro (data engineering expert)
│
└── static/
    └── index.html                 # Single-file frontend — HTML + CSS + JS, all SVG icons
```

---

## Environment Variables

```
GEMINI_API_KEY=...
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=...
CHROMA_PATH=./chroma_db
ANONYMIZED_TELEMETRY=False
SCRAPE_CRON_DAY=sun
SCRAPE_CRON_HOUR=2
```

ANONYMIZED_TELEMETRY=False suppresses harmless but noisy ChromaDB PostHog telemetry
errors that appear in logs due to a version mismatch between chromadb 0.5.23 and posthog.

---

## How to Run

```bash
# 1. Start Neo4j
docker-compose up -d

# 2. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 3. Start server
uvicorn main:app --reload --port 8000
```

The developer is on Windows — use PowerShell syntax for all API call examples:

```powershell
# Health check
Invoke-RestMethod -Uri "http://localhost:8000/health"

# Trigger scrape
Invoke-RestMethod -Uri "http://localhost:8000/admin/scrape" -Method POST -ContentType "application/json" -Body '{}'

# Query
Invoke-RestMethod -Uri "http://localhost:8000/api/query" -Method POST -ContentType "application/json" -Body '{"question": "What does the Stripe Payment Intent API do?"}'
```

Do NOT use curl syntax — on Windows PowerShell, curl is an alias for Invoke-WebRequest
and uses completely different parameter syntax.

---

## API Endpoints Reference

| Method | Route | Description |
|---|---|---|
| GET | / | Frontend UI |
| POST | /api/query | Main query — auto-routes lookup vs planning |
| GET | /api/apis | List all stored APIs |
| POST | /api/apis | Add a single API manually |
| DELETE | /api/apis/{id} | Delete an API |
| GET | /api/platforms | List platform names |
| GET | /api/categories | List category names |
| POST | /api/upload | Bulk import from .json/.csv/.txt/.pdf |
| POST | /admin/scrape | Trigger ingestion pipeline (background) |
| GET | /admin/scrape/status | Scrape job status |
| GET | /health | System health check |
| GET | /docs | FastAPI interactive docs |

### Query request body

```json
{
  "question": "How do I charge a customer?",
  "platform_filter": "Stripe",
  "category_filter": null
}
```

### Query response body

```json
{
  "answer": "...",
  "query_type": "lookup | planning",
  "sources": [
    {
      "name": "Stripe Create Payment Intent",
      "platform": "Stripe",
      "endpoint": "/v1/payment_intents",
      "relevance": 0.94,
      "source": "vector | graph"
    }
  ],
  "plan_steps": [
    {
      "step": 1,
      "api_name": "Stripe Create Payment Intent",
      "platform": "Stripe",
      "endpoint": "POST /v1/payment_intents",
      "purpose": "...",
      "parameters": ["amount (required) -> order total in paise"],
      "returns": "client_secret"
    }
  ]
}
```

---

## Data Model

Every API entry normalizes to APIEntry in models.py:

```
name              str   — short descriptive name
platform          str   — WhatsApp / Meta / Stripe / Twilio / SendGrid / Google Maps / Internal
category          str   — sub-grouping within platform
method            str   — GET / POST / PUT / PATCH / DELETE
endpoint          str   — URL path e.g. /v1/{phone-number-id}/messages
base_url          str   — e.g. https://graph.facebook.com
auth              str   — auth method description
parameters        list  — APIParameter objects (name, required, type, description, example)
response_fields   list  — key fields returned by the API
description       str   — full technical description
plain_explanation str   — non-technical plain English for end users
requires          list  — API names that must be called before this one
triggers          list  — events/APIs this call fires (e.g. webhooks)
precedes          list  — APIs typically called after this one
is_internal       bool  — True for internal company API wrappers
internal_notes    str   — internal-only context, environment notes
doc_url           str   — source documentation URL
```

---

## Ingestion Sources

| Platform | Method | Source |
|---|---|---|
| Twilio Messaging | OpenAPI JSON | github.com/twilio/twilio-oai — twilio_messaging_v1.json |
| Twilio Verify | OpenAPI JSON | github.com/twilio/twilio-oai — twilio_verify_v2.json |
| Twilio Lookup | OpenAPI JSON | github.com/twilio/twilio-oai — twilio_lookups_v2.json |
| SendGrid | OpenAPI YAML | github.com/twilio/sendgrid-oai — oai.yaml |
| Stripe | OpenAPI JSON | github.com/stripe/openapi — spec3.json |
| Google Maps | Manual definitions | 5 endpoints hardcoded in openapi_parser.py |
| WhatsApp | Curated JSON | ingestion/meta_api_definitions.json (7 entries) |
| Meta Graph API | Curated JSON | ingestion/meta_api_definitions.json (6 entries) |
| Instagram | Curated JSON | ingestion/meta_api_definitions.json (3 entries) |
| GA4 | Curated JSON | ingestion/ga4_api_definitions.json (9 entries) |
| Meta Ads | Curated JSON | ingestion/meta_ads_api_definitions.json (8 entries) |
| Meta Pixel / CAPI | Curated JSON | ingestion/meta_pixel_capi_definitions.json (7 entries) |
| Shopify | Curated JSON | ingestion/shopify_api_definitions.json (9 entries) |
| AppsFlyer | Curated JSON | ingestion/appsflyer_api_definitions.json (6 entries) |
| Firebase | Curated JSON | ingestion/firebase_api_definitions.json (6 entries) |

---

## Known Bugs and Issues

### Resolved — Meta scraper returned 0 blocks (2026-03-12)

Root cause: Meta's developer site blocks all headless browsers at the network level.
Even with a realistic Chrome user-agent and domcontentloaded wait strategy,
page.goto() times out on all Meta/WhatsApp/Instagram doc URLs.

Resolution: Replaced Playwright scraping for Meta platforms with a curated JSON file
(ingestion/meta_api_definitions.json) containing 16 hand-written API definitions
(7 WhatsApp, 6 Meta, 3 Instagram). The scheduler's _load_meta_definitions() method
reads this file during ingestion. Verified: all 16 entries load into ChromaDB and Neo4j.

The Playwright scraper is still used for single-URL scraping ("From Website" modal)
on non-Meta sites, with the following improvements applied:
- Realistic Chrome user-agent + 1920x1080 viewport
- Heading selectors expanded from h2/h3 to h1/h2/h3/h4
- Container-based fallback extraction (article, main, [role=main], .content)
- Wait strategy changed from networkidle to domcontentloaded

### Resolved — Frontend had emojis (2026-03-12)

All emoji/Unicode characters removed from static/index.html and replaced with inline SVGs:
- Platform filter close button (was Unicode cross)
- Scrape status indicators (were Unicode symbols for progress, success, failure)
Verified via regex grep: zero emoji/Unicode characters remain.

### Issue — Internal API wrappers pending

The user has internal API wrappers but details are not finalised. Do not prompt them
about this — they will raise it when ready. The template is at internal_api_template.json.

### Issue — Graph relationships may be sparse

The requires/triggers/precedes fields are extracted by Gemini Flash during structuring.
If the source doc does not clearly describe relationships, Gemini may return empty arrays.
This means Neo4j may have nodes but few edges, weakening planning query quality.
After full ingestion, check edge count in Neo4j browser:
  MATCH ()-[r]->() RETURN count(r)
If low, add relationships manually via POST /api/apis.

---

## Architecture Flows

### Ingestion

```
GitHub OpenAPI specs → openapi_parser.py → APIEntry list
                                         → Gemini Flash enrichment (plain_explanation + relationships)
                                         → ChromaDB upsert
                                         → Neo4j upsert

meta_api_definitions.json → scheduler._load_meta_definitions()
                          → APIEntry list (16 entries)
                          → ChromaDB upsert
                          → Neo4j upsert

Single URL ("From Website") → playwright_scraper.py (subprocess)
                            → raw HTML blocks
                            → structuring.py (Gemini Flash)
                            → APIEntry list
                            → ChromaDB upsert
                            → Neo4j upsert
```

### Lookup query

```
Question → classifier.py → lookup_handler.py
                         → vector_store.hybrid_search() (Vector + BM25 + RRF)
                         → reranker.rerank() (cross-encoder top 4)
                         → Gemini Flash
                         → QueryResponse (query_type: lookup)
```

### Planning query

```
Question → classifier.py → planning_handler.py
                         → Gemini Flash keyword extraction
                         → graph_store.find_apis_for_goal() (Neo4j traversal)
                         → vector_store.hybrid_search() (parameter details)
                         → reranker.rerank()
                         → Gemini Pro
                         → QueryResponse (query_type: planning, plan_steps: [...])
```

---

## Key Design Decisions

**No Anthropic/OpenAI** — developer only has a Gemini API key. Never introduce other providers.

**Gemini model strings** — use gemini-2.5-flash and gemini-2.5-pro. The 1.5 versions are deprecated.

**Playwright subprocess isolation** — Playwright requires asyncio subprocesses which conflict
with Windows ProactorEventLoop inside FastAPI. Running it as an isolated subprocess.run()
process is the only reliable solution on Windows. Used for single-URL scraping only; Meta
platforms use a curated JSON file instead because Meta blocks headless browsers entirely.

**Lookup handler tuning** — max_output_tokens increased from 600 to 1500, and context per
source increased from 800 to 1500 chars, for more detailed lookup answers.

**bge-large over ChromaDB default** — ChromaDB's bundled all-MiniLM-L6-v2 is insufficient
for technical documentation retrieval accuracy. bge-large-en-v1.5 is substantially better.

**BM25 alongside vectors** — API endpoint paths and parameter names are exact keywords.
Pure vector search misses exact matches. BM25 catches them. RRF combines both.

**Gemini Pro for planning and advisory** — Pro has stronger multi-hop reasoning for API sequence
generation and data engineering advisory answers. Flash is used everywhere else for speed and cost.

**Advisory handler uses general Gemini knowledge** — Unlike lookup (which only answers from KB context),
the advisory handler is permitted to use Gemini's general data engineering knowledge alongside KB context.
This is intentional — advisory questions like "why do Shopify and GA4 numbers differ" require domain
expertise that cannot be grounded purely in API documentation entries.

**One chunk per endpoint** — each APIEntry represents exactly one API endpoint. Never split
a single endpoint's documentation across multiple chunks. This is critical for accuracy.

---

## Developer Preferences — Read Before Every Response

- No emojis anywhere — not in chat messages, not in any code or UI built for this project
- Use SVGs where a visual element is needed, or no graphic at all
- Developer is on Windows — always use PowerShell syntax (Invoke-RestMethod) not curl
- Developer is an intern — keep explanations clear and avoid assuming deep knowledge
- Accuracy is the top priority for this system, speed is secondary
- The deployment target is an internal company server with Docker

---

## Pending Tasks in Priority Order

1. ~~Fix Playwright scraper~~ — DONE (2026-03-12): replaced with JSON file for Meta, improved Playwright for non-Meta URLs
2. ~~Remove all emojis from static/index.html~~ — DONE (2026-03-12): replaced with SVGs
3. ~~Add advisory query mode~~ — DONE (2026-03-12): third query type covering data engineering advisory, SQL, diagnostics, schema design
4. ~~Add missing data engineering platforms~~ — DONE (2026-03-12): GA4, Meta Ads, Meta Pixel/CAPI, Shopify, AppsFlyer, Firebase
5. Trigger full ingestion after startup to populate new platforms into ChromaDB + Neo4j
6. Add internal API wrapper entries once user finalises the details
7. Evaluate advisory answer quality on the 50 sample questions (see Data engineer's Assistant sample questions.pdf)
8. Evaluate graph relationship density in Neo4j — add manual edges if sparse
9. Update this HANDOVER.md after each work session
