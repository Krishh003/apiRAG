# API Knowledge Base RAG — v2

Hybrid RAG system for internal API documentation. Answers plain-English questions
about what APIs do, and generates step-by-step API call plans for specific goals.

---

## What's New in v2

| Feature | v1 | v2 |
|---|---|---|
| Embeddings | ChromaDB default (all-MiniLM) | **bge-large-en-v1.5** (higher accuracy) |
| Search | Vector only | **Hybrid: Vector + BM25** (Reciprocal Rank Fusion) |
| Reranking | None | **Cross-encoder reranker** |
| Graph layer | None | **Neo4j** — API relationship traversal |
| Query routing | Single mode | **Auto-classify: Lookup vs Planning** |
| Planning queries | Not supported | **Step-by-step API call plans with parameters** |
| Ingestion | Manual only | **OpenAPI parser + Playwright scraper + scheduler** |
| LLM | Gemini Flash | Flash (lookups) + **Pro (planning)** |

---

## Setup

### 1. Start Neo4j
```bash
cp .env.example .env
# Edit NEO4J_PASSWORD in .env first
docker-compose up -d
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Configure environment
```
GEMINI_API_KEY=your_key_here
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password_here
```

### 4. Run
```bash
uvicorn main:app --reload --port 8000
```

### 5. Populate knowledge base
Either trigger via UI (🔄 Run Scraper button) or API:
```bash
# Scrape all platforms
curl -X POST http://localhost:8000/admin/scrape -H "Content-Type: application/json" -d '{}'

# Scrape specific platforms only
curl -X POST http://localhost:8000/admin/scrape -H "Content-Type: application/json" \
  -d '{"platforms": ["Stripe", "Twilio"]}'
```

---

## Query Types

### Lookup
_"What does the WhatsApp Template Message API do?"_
→ Fast retrieval via hybrid search + Gemini Flash → plain English answer

### Planning
_"How do I charge a customer for their order?"_
→ Graph traversal + hybrid search + Gemini Pro → step-by-step call plan with parameters

The system auto-classifies queries. You can also force a mode in the UI.

---

## Ingestion Sources

| Platform | Method | Source |
|---|---|---|
| Twilio (Messaging, Verify, Lookup) | OpenAPI JSON | github.com/twilio/twilio-oai |
| SendGrid | OpenAPI YAML | github.com/twilio/sendgrid-oai |
| Stripe | OpenAPI JSON | github.com/stripe/openapi |
| Google Maps | Manual definitions | Built-in (5 key endpoints) |
| WhatsApp Cloud API | Playwright scraper | developers.facebook.com |
| Meta Graph API | Playwright scraper | developers.facebook.com |
| Instagram Graph API | Playwright scraper | developers.facebook.com |

---

## Internal API Wrappers

Use `internal_api_template.json` as a starting point. Upload via the UI or API:

```bash
curl -X POST http://localhost:8000/api/upload \
  -F "file=@internal_api_template.json"
```

Or add one at a time via the **+ Add API** button in the UI (check "Internal API wrapper").

---

## API Endpoints

| Method | Route | Description |
|---|---|---|
| `POST` | `/api/query` | Ask a question (auto-routes lookup vs planning) |
| `GET` | `/api/apis` | List all stored APIs |
| `POST` | `/api/apis` | Add a single API manually |
| `DELETE` | `/api/apis/{id}` | Delete an API |
| `GET` | `/api/platforms` | List all platforms |
| `GET` | `/api/categories` | List all categories |
| `POST` | `/api/upload` | Bulk import from file |
| `POST` | `/admin/scrape` | Trigger ingestion pipeline |
| `GET` | `/admin/scrape/status` | Check scrape status |
| `GET` | `/health` | System health check |

Interactive docs: `http://localhost:8000/docs`

---

## Architecture

```
Query → Classifier → Lookup Handler  → Hybrid Search → Reranker → Gemini Flash
                  ↘ Planning Handler → Graph Traversal
                                     + Hybrid Search → Reranker → Gemini Pro
```

```
Ingestion → OpenAPI Parser (Twilio/Stripe/SendGrid/Maps)  ↘
          → Playwright Scraper (WhatsApp/Meta/Instagram)  → Structuring (Gemini Flash)
          → Manual Entry / File Upload                    ↗
                                                          → ChromaDB + Neo4j
```

---

## Scheduled Scraping

By default, the scraper runs every Sunday at 02:00 IST.
Configure in `.env`:
```
SCRAPE_CRON_DAY=sun
SCRAPE_CRON_HOUR=2
```
