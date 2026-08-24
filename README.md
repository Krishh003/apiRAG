# API Knowledge Base RAG

> A retrieval-augmented knowledge system for answering, comparing, and planning workflows across company APIs using hybrid retrieval, reranking, and graph traversal.

**Python · FastAPI · ChromaDB · Neo4j · Gemini · BM25 · BGE · Cross-Encoder · Playwright**

## Engineering highlights

| Area | Implementation |
| --- | --- |
| Retrieval | Dense vector search + BM25 fused with Reciprocal Rank Fusion |
| Ranking | Cross-encoder reranking for higher-precision source selection |
| Reasoning | Four query modes: lookup, planning, advisory, and comparison |
| Workflow planning | Neo4j relationship traversal for multi-hop API workflows |
| Ingestion | OpenAPI parsing, curated definitions, Playwright scraping, uploads, and manual entry |
| Backend | FastAPI service with query, ingestion, administration, and health endpoints |
| Operations | Persistent ChromaDB storage and scheduled ingestion with APScheduler |

The goal is to let non-technical users ask plain-English questions such as **“How do I charge a customer for their order?”** or **“Why do Shopify numbers differ from GA4?”** and receive answers grounded in the underlying API knowledge base.

---

## How it works

Every question is classified and routed to a specialized retrieval strategy:

| Mode | Example | Strategy |
| --- | --- | --- |
| **Lookup** | “What does the WhatsApp Send Message API do?” | Hybrid search → rerank → Gemini Flash |
| **Planning** | “How do I charge a customer for their order?” | Graph traversal + hybrid search → rerank → Gemini Pro |
| **Advisory** | “Why do Shopify numbers differ from GA4?” | KB context + hybrid retrieval → Gemini Pro |
| **Comparison** | “Capture vs confirm a PaymentIntent?” | Per-concept retrieval → rerank → Gemini Flash |

```text
User Question
      |
      v
  Classifier
      |
      +---> Lookup ------> Hybrid Search ----------> Rerank -> Answer
      +---> Planning ----> Neo4j + Hybrid Search --> Rerank -> Plan
      +---> Advisory ----> Hybrid Search ----------> Rerank -> Advice
      +---> Comparison --> Per-concept Retrieval --> Rerank -> Comparison
```

### Retrieval pipeline

```text
Query
  |---> BGE vector search ----+
  |                           +--> Reciprocal Rank Fusion --> Cross-Encoder --> LLM
  +---> BM25 keyword search --+
```

### Ingestion pipeline

```text
OpenAPI specs -----------+
Curated API definitions -+
Playwright scraping -----+--> Normalize --> ChromaDB + Neo4j
File uploads ------------+
Manual entry ------------+
```

---

## Features

- Automatic four-way query classification
- Hybrid semantic + keyword retrieval
- Cross-encoder reranking
- Graph-based multi-hop workflow planning
- API knowledge across Twilio, SendGrid, Stripe, Google Maps, WhatsApp, Meta, Instagram, GA4, Meta Ads, Pixel/CAPI, Shopify, AppsFlyer, and Firebase
- OpenAPI, JSON, scraping, upload, and manual ingestion paths
- Scheduled ingestion with APScheduler
- Responsive frontend with theme, mode, platform-filter, and file-upload controls

---

## Tech stack

| Component | Technology |
| --- | --- |
| Backend | FastAPI 0.115.5 / Python |
| LLM | Google Gemini 2.5 Flash + Pro |
| Vector DB | ChromaDB 0.5.23 |
| Embeddings | BAAI/bge-large-en-v1.5 |
| Keyword search | rank_bm25 + Reciprocal Rank Fusion |
| Reranker | cross-encoder/ms-marco-MiniLM-L-6-v2 |
| Graph DB | Neo4j 5.26 Community |
| Scraping | Playwright 1.49.0 |
| Scheduling | APScheduler 3.10.4 |
| Frontend | HTML / CSS / JavaScript |

---

## Quick start

### Prerequisites

- Python 3.10+
- Docker
- Google AI Studio API key

### 1. Clone and configure

```bash
git clone https://github.com/Krishh003/apiRAG.git
cd apiRAG
cp .env.example .env
```

Configure:

```env
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

### 4. Start the API

```bash
uvicorn main:app --reload --port 8000
```

The application is available at `http://localhost:8000`, with Swagger documentation at `http://localhost:8000/docs`.

### 5. Populate the knowledge base

From the UI, use **Run Scraper**, or call the administration endpoint:

```bash
curl -X POST http://localhost:8000/admin/scrape \
  -H "Content-Type: application/json" \
  -d '{}'
```

---

## API surface

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/query` | Ask a question and auto-route it |
| `GET` | `/api/apis` | List stored API entries |
| `POST` | `/api/apis` | Add an API entry |
| `DELETE` | `/api/apis/{id}` | Remove an entry |
| `GET` | `/api/platforms` | List platforms |
| `GET` | `/api/categories` | List categories |
| `POST` | `/api/upload` | Import JSON, CSV, TXT, PDF, or Markdown |
| `POST` | `/admin/scrape` | Trigger the ingestion pipeline |
| `POST` | `/admin/scrape/url` | Scrape one URL |
| `GET` | `/admin/scrape/status` | Inspect ingestion status |
| `GET` | `/health` | Service health check |

See [docs/api-reference.md](docs/api-reference.md) for full schemas.

---

## Repository structure

```text
apiRAG/
├── main.py                 # FastAPI application and routes
├── models.py               # Domain and request/response models
├── query/                  # Query classification and specialized handlers
├── retrieval/              # Vector/BM25 retrieval, Neo4j, reranking
├── ingestion/              # Parsing, scraping, normalization, scheduling
├── static/                 # Browser UI
├── docs/                   # Architecture and operational documentation
├── docker-compose.yml      # Neo4j service
├── requirements.txt
└── .env.example
```

---

## Documentation

- [Architecture](docs/architecture.md) — system design and data flow
- [Query Modes](docs/query-modes.md) — routing and retrieval strategies
- [Ingestion Guide](docs/ingestion.md) — adding platforms and sources
- [API Reference](docs/api-reference.md) — endpoints and schemas
- [Configuration](docs/configuration.md) — environment variables
- [Deployment](docs/deployment.md) — production deployment
- [Troubleshooting](docs/troubleshooting.md) — common issues
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- [Handover](HANDOVER.md)

---

## License

Internal use only. Proprietary to the organization.
