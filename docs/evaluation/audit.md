# Repository audit (2026-10-20)

Audit target: local working tree based on `1edd28e`, including pre-existing staged
changes. No application source or UI changes are part of this evaluation task.
Read all Python implementation modules, frontend request/render paths, dependency
and Docker configuration, existing docs and test inventory before implementation.
Inventoried curated JSON records (59); did not export local Chroma or private PDFs.

## Query modes

| Mode | Actual path | Generation configuration |
|---|---|---|
| Lookup | hybrid top 8, rerank top 4, 1500 characters per context source | Gemini 2.5 Flash, temperature .2, max 1500 output tokens |
| Planning | Flash keywords, Neo4j goal traversal, hybrid top 10, rerank top 6; graph context first, at most 8 context entries | Gemini 2.5 Pro, .1, max 1500; Flash keywords temperature 0 |
| Advisory | hybrid top 8, rerank top 4; continues without context on retrieval failure; explicitly permits general knowledge | Gemini 2.5 Pro, .3, max 2500 |
| Comparison | full-query top 6 infers platforms, Flash extracts up to 4 concepts, per-concept search/rerank selects one source; fallback to original results | Gemini 2.5 Flash, .2, max 1500 |

`query/classifier.py` counts regex matches. Highest count wins; only ties use
advisory > comparison > planning > lookup. No matches invokes Flash; API errors
default to lookup. This is more specific than the priority summary in old docs.
`main.py` auto-routes; the UI sends a question and optional platform filter.

## Retrieval and ingestion

- `retrieval/vector_store.py`: CPU SentenceTransformer BAAI/bge-large-en-v1.5
  (1024 dimensions), persistent Chroma cosine collection `api_docs_v2`. The
  pre-existing staged change also supports bge-m3 in a separate collection.
  One document per endpoint; name, platform, category, method, endpoint, auth,
  first 10 parameters, descriptions and relationship names are serialized.
  Base URL, response fields and internal notes are omitted from searchable text.
- BM25Okapi uses lowercase whitespace splitting; only strictly positive scores
  survive. Index rebuilt from all stored documents after writes/deletes.
- Hybrid searches each branch to 2 * requested depth. RRF k=60, with a
  nonstandard missing-rank contribution of 1/(60 + union_size + 1), rather than
  zero. Metadata filters apply to the dense branch but not BM25. Fetch/re-sort
  rounds RRF scores to four decimals, introducing ties. Preserve these behaviors;
  any canonical RRF analysis must be labeled separately.
- `retrieval/reranker.py`: cached cross-encoder/ms-marco-MiniLM-L-6-v2,
  max_length=512 tokens, but input document first truncated to **512 characters**.
  Sigmoid scores rounded to four decimals. Model/predict failures return original
  ordering silently to callers; benchmark must detect this and fail the stage.
- Neo4j nodes API, Platform, Category; REQUIRES, PRECEDES, TRIGGERS edges created
  by fuzzy name matching across platforms. Goal query matches keywords and
  expands outgoing paths up to 3 hops with unordered LIMIT 8. Named workflow
  helper uses APOC, up to 4 hops and LIMIT 10; planning calls goal query instead.
  Graph context precedes vector context and is not jointly reranked. Duplicate
  names can suppress richer vector parameter context.
- OpenAPI: public GitHub specs via httpx, shallow local ref resolution, selected
  Stripe/SendGrid/WhatsApp paths; Google Maps is hardcoded definitions. Gemini
  Flash enriches explanations and edges. Curated JSON loader maps category to
  platform and drops parameter/relationship fields. Playwright runs a subprocess,
  extracts heading/container text, then Gemini structures it. Scheduled weekly
  ingestion and manual API/upload routes write both stores without a transaction.
- Upload supports JSON, CSV, TXT, PDF pages and Markdown sections. Manual/upload
  ingestion marks entries internal. It can swallow errors while routes report
  success. Deletes remove vector entries without deleting graph nodes.

## Existing checks and limitations

No automated test suite or CI was present. `test_*` files are import examples,
not tests. `audit_graph.py` reports counts, not planning correctness. The staged
`evaluation/compare_embeddings.py` has 18 queries, substring/platform labels,
counts missing labels as perfect hits/RR, and aggregates them despite claiming
ground-truth-only MRR. Its outputs cannot establish the requested ablations.

Startup requires Gemini credentials, model weights, Chroma and reachable Neo4j;
starts a scheduler. Synchronous CPU/model calls inside the async query route can
block concurrent requests. Confidence is a heuristic source-score average, not
calibrated factual accuracy. Advisory answers need separate correctness and KB
grounding judgments. No built-in auth, upload limits or URL allowlist; do not run
load tests against shared/customer deployments. No service changes are made here.

Local `.venv` points to a missing Miniconda Python. System Python 3.10.11 exists;
benchmark ML dependencies initially absent. Do not treat setup failures as passes.

## Offline versus external evaluation

| Experiment | Requirements | Isolation |
|---|---|---|
| Metrics, dataset validation, human review scoring | Python standard library | no credentials/network |
| BM25 | rank_bm25, numpy | synthetic corpus only |
| Dense, hybrid, rerank | Chroma, sentence-transformers and cached weights | fresh temporary Chroma store, never production path |
| Graph ablation | dedicated empty Neo4j database and evaluation credentials | explicit opt-in, synthetic API nodes only |
| Optional answers | GEMINI_API_KEY and cached local retrieval | sequential, bounded calls; four existing handlers, no scheduler |
| HTTP end-to-end | separately started isolated app with synthetic corpus | loopback only, bounded concurrency, explicit opt-in |

Downloads require network once; warmed model inference can run offline. This task
does not read `.env`, ingest existing customer data, or start the production app.

## Permissions and provenance

GitHub metadata checked 2026-10-20: repository `Krishh003/apiRAG` is **public**;
connected account has admin/push permission. README license says **internal use
only, proprietary**. Git permission does not prove company publication consent.
Prepare a scoped local commit; no remote publication until that discrepancy is
resolved. Original synthetic documentation under `evaluation/data/` is the only
benchmark corpus. Do not copy existing internal templates, PDFs or live stores.
Existing staged retrieval/UI/config/embedding-evaluation work belongs to the user
and must stay outside the benchmark commit.
