# Verification record

Executed locally on 2026-10-20 with system Python 3.10.11 and the existing
Python 3.10-compatible project libraries (see setup instructions).

| Check | Observed result |
|---|---|
| `python -m unittest discover -s evaluation/tests -v` | 24 tests passed |
| `python -m evaluation.dataset` | 25 documents, 100 questions, 87 answerable; hashes recorded |
| Full offline retrieval run, three repeats | BM25 completed; dense setup failed with missing cached weights; dependent hybrid/rerank incomplete |
| Rescore saved predictions | Metrics recomputed without model calls |
| Prepare and score empty review packet | 100 pending reviews; quality/abstention scores null |
| Report generation | Predictions validated against saved aggregates before tables and PNG plots |
| Confidentiality review | Added data is original synthetic; no `.env`, live store, PDFs or internal templates included |
| Independent code review | Three findings fixed: warmup evidence, inference-failure statuses/counts, model provenance; follow-up found no further important issues |

Tests include deterministic ranking math, multi-source recall, cutoff handling,
missing qrels, duplicates, seeded CIs, label integrity, real BM25 integration,
production serializer/search parity, reranker truncation, empty/OOV queries,
first-inference and request failures, review validation and loopback-only targets.

Known existing warning: production `APIEntry.Config` uses Pydantic's deprecated
class-based configuration. Production files were preserved.

No learned inference, graph service, Gemini generation, human answer adjudication,
HTTP application load test or live UI regression test passed in this session;
these remain unrun/incomplete. The reviewer inspected code and documentation,
not service-backed behavior. No remote push or publication was performed.
