# Configuration Reference

All configuration is managed through environment variables in a `.env` file at the project root. Copy `.env.example` to get started:

```bash
cp .env.example .env
```

---

## Environment Variables

### Required

| Variable | Description | Example |
| --- | --- | --- |
| `GEMINI_API_KEY` | Google AI Studio API key. Get one at [aistudio.google.com](https://aistudio.google.com) | `AIza...` |
| `NEO4J_PASSWORD` | Password for the Neo4j database. Must match the password set in docker-compose.yml | `your_secure_password` |

### Optional (with defaults)

| Variable | Default | Description |
| --- | --- | --- |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j bolt connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `CHROMA_PATH` | `./chroma_db` | Directory for ChromaDB persistent storage |
| `ANONYMIZED_TELEMETRY` | `False` | Set to `False` to suppress ChromaDB PostHog telemetry errors |
| `SCRAPE_CRON_DAY` | `sun` | Day of week for scheduled ingestion (mon-sun) |
| `SCRAPE_CRON_HOUR` | `2` | Hour for scheduled ingestion (0-23, Asia/Kolkata timezone) |

---

## LLM Models

The system uses two Gemini models. These are configured in the handler source files, not via environment variables:

| Model | Used By | Purpose |
| --- | --- | --- |
| `gemini-2.5-flash` | Lookup handler, Comparison handler, Classifier, Structuring | Fast responses, classification, enrichment |
| `gemini-2.5-pro` | Planning handler, Advisory handler | Complex reasoning, multi-hop planning |

**Important**: Only Gemini models are supported. Do not substitute with OpenAI or Anthropic models.

---

## Embedding Model

| Setting | Value |
| --- | --- |
| Model | `BAAI/bge-large-en-v1.5` |
| Framework | sentence-transformers 2.7.0 |
| Dimensions | 1024 |

Configured in [retrieval/vector_store.py](../retrieval/vector_store.py). The model is downloaded automatically on first run.

---

## Reranker Model

| Setting | Value |
| --- | --- |
| Model | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Framework | transformers |
| Load behavior | Lazy (loaded on first query, then cached) |

Configured in [retrieval/reranker.py](../retrieval/reranker.py).

---

## Neo4j (Docker)

Neo4j runs as a Docker container defined in [docker-compose.yml](../docker-compose.yml):

| Port | Purpose |
| --- | --- |
| 7474 | Neo4j Browser UI (http://localhost:7474) |
| 7687 | Bolt protocol (used by the Python driver) |

The container uses the `neo4j:5.26-community` image with the APOC plugin enabled.

**Data persistence**: Neo4j data is stored in a Docker named volume (`neo4j_data`). Data survives container restarts but not `docker-compose down -v`.

---

## ChromaDB

| Setting | Value |
| --- | --- |
| Collection name | `api_docs_v2` |
| Similarity metric | Cosine |
| Storage | Persistent local directory (`./chroma_db/`) |

The ChromaDB directory is created automatically on first run. Add `chroma_db/` to `.gitignore` to avoid committing vector data.

---

## Scheduler

| Setting | Value |
| --- | --- |
| Scheduler type | APScheduler BackgroundScheduler |
| Trigger | Cron (weekly) |
| Timezone | Asia/Kolkata |
| Default schedule | Every Sunday at 02:00 |

The scheduler starts automatically during FastAPI lifespan startup. It can be disabled by removing the scheduler initialization from [main.py](../main.py).
