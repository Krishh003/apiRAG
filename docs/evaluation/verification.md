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
not service-backed behavior.

## Continuation

- 31 unit/integration tests passed after adding the lexical answer control,
  per-model pacing and quota suppression, actual-answer review validation, and
  isolated HTTP route tests.
- Two bounded 12-question Gemini diagnostics ran; the paced run produced seven
  answer texts and five application failures. These are not correctness scores.
- Four concurrent loopback requests reached the real query route, all returning
  handled quota failures; healthy HTTP performance is not established.
- Synthetic answer/prompt/call evidence was checked for credential patterns before
  copying to `results/`. No key or `.env` content is included.
- Reviewer findings led to an explicit process-key check before importing the
  HTTP route, suppression of its automatic dotenv loading, expanded source hashes
  and generation-setting records for future runs. Earlier service manifests remain
  explicitly limited; they were not retroactively relabeled as complete.
- A real Chroma lifecycle test reproduced Windows `WinError 32` on temporary HNSW
  files. Evaluation adapters now stop their owned Chroma system before removing
  the temporary directory, including error paths after initialization. All 32
  tests passed after the fix. This test uses deterministic test embeddings and
  is not a learned-retrieval measurement.
