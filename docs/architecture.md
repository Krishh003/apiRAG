# Architecture

This document describes the system architecture, data flow, component responsibilities, and key design decisions behind the API Knowledge Base RAG v2.

---

## System Overview

The system is a Retrieval-Augmented Generation (RAG) application with four specialized query handlers. Each handler uses a different combination of retrieval strategies and LLM models to answer questions about company APIs.

```
                                    +------------------+
                                    |    Frontend UI   |
                                    |  (static/*)      |
                                    +--------+---------+
                                             |
                                             v
                                    +------------------+
                                    |   FastAPI App     |
                                    |   (main.py)       |
                                    +--------+---------+
                                             |
                          +------------------+------------------+
                          |                                     |
                   Query Pipeline                        Ingestion Pipeline
                          |                                     |
              +-----------+-----------+              +----------+----------+
              |                       |              |          |          |
        +-----+------+        +------+-----+   OpenAPI    Curated    Playwright
        | Classifier  |        | Handlers   |   Parser    JSON       Scraper
        | (query/)    |        | (query/)   |   (ingestion/)
        +-----+------+        +------+-----+
              |                       |
              v                       v
    +------------------+    +-------------------+
    |   Retrieval       |    |    LLM (Gemini)   |
    | - ChromaDB        |    | - Flash (fast)    |
    | - BM25            |    | - Pro (reasoning) |
    | - Neo4j           |    +-------------------+
    | - Reranker        |
    +------------------+
```

---

## Core Components

### 1. Query Pipeline

The query pipeline processes user questions through four stages:

**Stage 1: Classification** ([query/classifier.py](../query/classifier.py))
- Fast keyword heuristics check for advisory, comparison, and planning signals
- Falls back to Gemini Flash for ambiguous queries
- Priority order: advisory > comparison > planning > lookup
- Returns one of: `"lookup"`, `"planning"`, `"advisory"`, `"comparison"`

**Stage 2: Retrieval** ([retrieval/](../retrieval/))
- **Hybrid search**: Vector similarity (ChromaDB + bge-large-en-v1.5) combined with BM25 keyword matching via Reciprocal Rank Fusion (RRF)
- **Graph traversal**: Neo4j relationship traversal for planning queries (finds multi-hop API workflows)
- Each handler configures its own retrieval strategy (top_k, filters, per-concept vs full-question)

**Stage 3: Reranking** ([retrieval/reranker.py](../retrieval/reranker.py))
- Cross-encoder model (ms-marco-MiniLM-L-6-v2) jointly scores (query, document) pairs
- Raw logits passed through sigmoid to produce [0.0, 1.0] relevance scores
- Supports per-document `match_query` override (used by comparison handler)
- Lazy-loaded on first use, then cached

**Stage 4: Generation**
- Gemini Flash for lookup and comparison (fast, cost-effective)
- Gemini Pro for planning and advisory (stronger multi-hop reasoning)
- Each handler has a specialized system prompt targeting non-technical users

### 2. Retrieval Layer

#### ChromaDB Vector Store ([retrieval/vector_store.py](../retrieval/vector_store.py))

- **Collection**: `api_docs_v2` with cosine similarity
- **Embeddings**: BAAI/bge-large-en-v1.5 via sentence-transformers
- **Document format**: Each entry combines name, platform, category, endpoint, parameters, description, plain_explanation, and relationships into a single searchable document
- **Persistent storage**: `./chroma_db/` directory

#### BM25 Keyword Search ([retrieval/vector_store.py](../retrieval/vector_store.py))

- In-memory BM25 index rebuilt on every upsert
- Catches exact keyword matches that vector search misses (endpoint paths, parameter names)
- Combined with vector results via Reciprocal Rank Fusion (RRF)

#### Neo4j Graph Store ([retrieval/graph_store.py](../retrieval/graph_store.py))

- **Node types**: API, Platform, Category
- **Relationship types**: BELONGS_TO (API->Platform), IN_CATEGORY (API->Category), REQUIRES, TRIGGERS, PRECEDES (API->API)
- **Indexes**: On platform and category; unique constraint on (name, platform)
- Used primarily by the planning handler for multi-hop workflow discovery

### 3. Ingestion Pipeline

Three ingestion sources feed into a unified storage layer:

| Source | Parser | Enrichment |
|---|---|---|
| OpenAPI specs (GitHub) | [openapi_parser.py](../ingestion/openapi_parser.py) | Gemini Flash (plain_explanation + relationships) |
| Curated JSON files | [scheduler.py](../ingestion/scheduler.py) `_load_json_definitions()` | Pre-written (no LLM needed) |
| Playwright scraping | [playwright_scraper.py](../ingestion/playwright_scraper.py) | [structuring.py](../ingestion/structuring.py) (Gemini Flash) |

All entries normalize to the `APIEntry` schema (defined in [models.py](../models.py)) before being upserted into both ChromaDB and Neo4j.

### 4. Data Model

Every API endpoint is represented as an `APIEntry`:

```
APIEntry
├── Identity: name, platform, category, version
├── Technical: method, endpoint, base_url, auth, parameters[], response_fields[]
├── Documentation: description, plain_explanation, doc_url
├── Relationships: requires[], triggers[], precedes[]
└── Internal: is_internal, internal_notes
```

The `parameters` field contains `APIParameter` objects with: name, required, type, description, example.

---

## Design Decisions

### Why hybrid search (vector + BM25)?

Pure vector search misses exact keyword matches that are critical for API documentation. Endpoint paths like `/v1/payment_intents` and parameter names like `phone_number_id` are exact strings that BM25 matches precisely. RRF combines both ranking signals without requiring score calibration.

### Why bge-large over ChromaDB's default embeddings?

ChromaDB bundles all-MiniLM-L6-v2 by default. Testing showed it was insufficient for distinguishing between similar API endpoints in technical documentation. bge-large-en-v1.5 produced substantially better retrieval accuracy for this domain.

### Why two Gemini models (Flash + Pro)?

Flash is faster and cheaper, suitable for straightforward lookup and comparison queries where the retrieved context is sufficient. Pro has stronger multi-hop reasoning, necessary for planning queries (sequencing multiple API calls) and advisory queries (synthesizing cross-platform data engineering knowledge).

### Why per-concept retrieval in comparison mode?

Scoring all sources against the full comparison question (e.g., "What is the difference between X and Y?") produces near-zero relevance scores because the cross-encoder penalizes the mismatch between a concept-specific document and a comparison-framed query. Retrieving and scoring each source against its own concept produces meaningful scores (typically 80-100%).

### Why curated JSON for Meta platforms?

Meta's developer documentation site blocks all headless browsers at the network level. Meta published an official OpenAPI repository (github.com/facebook/openapi) in late 2025, but only the WhatsApp Cloud API spec is available so far. Other Meta platforms (Graph, Instagram, Ads, Pixel) use curated JSON until official specs are published.

### Why Playwright subprocess isolation?

On Windows, Playwright's asyncio requirements conflict with FastAPI's ProactorEventLoop. Running Playwright as an isolated `subprocess.run()` call is the only reliable solution on Windows.

### Why one chunk per endpoint?

Splitting a single endpoint's documentation across multiple chunks degrades retrieval accuracy. Each `APIEntry` represents exactly one API endpoint, ensuring the retriever always returns complete information.

### Why threshold-filtered confidence?

Low-scoring fallback sources (relevance < 0.15) can drag down the mean confidence score. Filtering them before computing the mean gives a more accurate representation of answer quality. The comparison handler doesn't need this because per-concept retrieval produces uniformly high scores.

---

## Data Flow Diagrams

### Query Flow (Lookup)

```
1. User submits question
2. classifier.py runs keyword heuristics
3. If ambiguous, Gemini Flash classifies
4. lookup_handler.py called
5. vector_store.hybrid_search(question, top_k=6)
   a. ChromaDB vector search (cosine similarity)
   b. BM25 keyword search
   c. RRF merges rankings
6. reranker.rerank(question, candidates, top_k=4)
7. Sources with relevance < 0.15 filtered
8. Gemini Flash generates answer from top sources
9. Response returned with answer, sources, confidence
```

### Query Flow (Planning)

```
1. classifier.py identifies planning intent
2. planning_handler.py called
3. Gemini Flash extracts keywords from question
4. graph_store.find_apis_for_goal(keywords)
   a. Neo4j Cypher queries traverse REQUIRES/PRECEDES edges
   b. Returns ordered API sequence
5. vector_store.hybrid_search() fills in parameter details
6. reranker.rerank() scores and filters
7. Gemini Pro generates step-by-step plan
8. Response includes plan_steps[] with endpoint, parameters, returns
```

### Ingestion Flow

```
1. Trigger: POST /admin/scrape, UI button, or APScheduler cron
2. scheduler.run_scrape_pipeline(platforms)
3. For each platform:
   a. OpenAPI: fetch spec from GitHub -> parse operations -> Gemini enrichment
   b. Curated JSON: load file -> map to APIEntry schema
   c. Playwright: navigate URL -> extract blocks -> Gemini structuring
4. For each APIEntry:
   a. ChromaDB upsert (vector + BM25 index rebuild)
   b. Neo4j upsert (nodes + relationships)
5. Status updated: GET /admin/scrape/status
```
