# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Pending
- Re-ingestion to load WhatsApp OpenAPI entries and expanded Meta/Instagram definitions
- Frontend: comparison badge, advisory/comparison mode buttons, split HTML/CSS/JS
- Internal API wrapper entries (awaiting finalized details)
- Advisory answer quality evaluation against 50 sample questions
- Graph relationship density audit

---

## [2.3.0] - 2026-03-17

### Added
- **Comparison query mode** with dedicated handler (`query/comparison_handler.py`)
- Per-concept retrieval: each source is searched and scored against its own concept, not the full comparison question
- Platform coherence filtering: infers relevant platforms from initial search to prevent cross-platform noise
- `COMPARISON_SIGNALS` keyword set in classifier for automatic detection
- Threshold-filtered confidence in lookup and planning handlers (sources with relevance < 0.15 excluded from mean)
- Reranker `match_query` support: per-document custom query strings for scoring

### Changed
- Classifier upgraded from 3-way (lookup/planning/advisory) to 4-way (+ comparison)
- Classification priority updated: advisory > comparison > planning > lookup

### Fixed
- Comparison questions no longer return ~36% confidence (was caused by scoring concept-specific documents against comparison-framed queries)

---

## [2.2.0] - 2026-03-13

### Added
- WhatsApp Cloud API ingestion from Meta's official OpenAPI spec (`github.com/facebook/openapi`, v23.0)
- `parse_meta_whatsapp()` function in `openapi_parser.py` with 22-path endpoint filter
- Gemini enrichment for WhatsApp entries (plain_explanation + relationship extraction)
- 4 new Meta/Instagram entries: GET /me, GET /{page-id}/conversations, GET /{video-id}/insights, GET /{ig-user-id}, GET /{ig-hashtag-id}/recent_media

### Changed
- WhatsApp ingestion method: curated JSON replaced with official OpenAPI spec parsing
- Meta API definitions expanded from 9 to 13 entries

### Removed
- 7 hand-written WhatsApp entries from `meta_api_definitions.json` (replaced by OpenAPI-parsed entries)

---

## [2.1.0] - 2026-03-12

### Added
- **Advisory query mode** with dedicated handler (`query/advisory_handler.py`)
- Data engineering expert persona system prompt targeting non-technical users
- Advisory keyword detection in classifier (why, should, design, SQL, schema, diagnose)
- 6 new curated JSON platform files: GA4 (9 entries), Meta Ads (8), Meta Pixel/CAPI (7), Shopify (9), AppsFlyer (6), Firebase (6)
- File upload endpoint (`POST /api/upload`) supporting .json, .csv, .txt, .pdf, .md
- Upload File tab in frontend Add API modal (drag-and-drop)
- Curated JSON definitions for Meta Graph API (6 entries) and Instagram (3 entries)
- SVG icons replacing all emoji/Unicode characters in frontend

### Changed
- Classifier upgraded from 2-way (lookup/planning) to 3-way (+ advisory)
- Advisory handler permits Gemini to use general knowledge (KB context is supplementary grounding)
- Lookup handler output tuned: max_output_tokens 600 -> 1500, context per source 800 -> 1500 chars

### Fixed
- Playwright scraper: improved selectors (h1-h4), container-based fallback extraction, realistic user-agent
- All emoji/Unicode characters removed from frontend and replaced with inline SVGs

---

## [2.0.0] - 2026-03-11

### Added
- **Hybrid search**: Vector similarity (ChromaDB) + BM25 keyword matching via Reciprocal Rank Fusion
- **Cross-encoder reranker** (ms-marco-MiniLM-L-6-v2) for high-precision source selection
- **Neo4j graph store** for API relationship traversal (REQUIRES, TRIGGERS, PRECEDES)
- **Planning query mode** with step-by-step API call plan generation (Gemini Pro)
- **Query classifier** (keyword heuristics + Gemini Flash fallback)
- **OpenAPI ingestion pipeline** for Twilio (3 specs), SendGrid, Stripe, Google Maps
- **Playwright scraper** for documentation URLs (subprocess-isolated for Windows)
- **Gemini Flash enrichment** during ingestion (plain_explanation + relationship extraction)
- **APScheduler** weekly cron for automated ingestion
- Upgraded embeddings from all-MiniLM to bge-large-en-v1.5

### Changed
- Complete architecture rewrite from v1
- Dual LLM strategy: Gemini Flash (lookup, classification) + Gemini Pro (planning)
- ChromaDB collection renamed to `api_docs_v2`

---

## [1.0.0] - 2026-03-10

### Added
- Initial RAG system with FastAPI backend
- ChromaDB vector store with default embeddings (all-MiniLM-L6-v2)
- Single query mode (lookup only)
- Gemini Flash for answer generation
- Basic frontend chat interface
- Manual API entry via POST endpoint
