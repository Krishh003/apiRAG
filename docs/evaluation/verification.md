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

At the initial pass, learned inference, graph service, Gemini generation, human
answer adjudication, HTTP application load tests and live UI regressions were
unrun/incomplete. Subsequent experiments are recorded below. The initial review
covered code and documentation, not service-backed behavior.

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
- A forced post-construction population failure reproduced a second Windows file
  lock. The adapter now closes its index before re-raising that failure. All 33
  tests passed in 26.895 seconds after the fix, including both real Chroma cleanup
  paths. The full test command required execution outside the sandbox: Windows
  asyncio's local socketpair blocked inside the sandbox (confirmed by traceback).
  Test handlers are mocked; no external model calls occur in this suite.
- All 34 tests passed in 28.083 seconds after adding atomic JSONL checkpoints.
  The regression verifies that a serialization failure preserves the previous
  complete predictions and removes temporary files. A learned run had stopped
  with Windows `OSError` errno 22 while reopening its checkpoint; the underlying
  OS error was not reproducible with a sibling-file probe. That interrupted run
  remains explicitly incomplete in `results/learned-02/`.
- `results/learned-03/` completed all four retrieval configurations, each with 300
  attempts and zero failures. The 1,200 saved predictions were rescored, exactly
  matching all aggregate retrieval metrics and paired deltas in `summary.json`.
  Model revisions and hashes were recorded for both loaded CPU models. Report
  tables and PNG plots were regenerated from this completed run; the retrieval
  plot was visually inspected. Twelve two-worker hybrid requests had zero failures.
- Independent review found no further important issues in the population cleanup
  fix or atomic checkpoint writer. Earlier setup failures and the interrupted
  run are retained and excluded from the completed experiment's aggregates.
- The separate Neo4j experiment completed 12 planning queries against a dedicated
  empty portable server. Verification matched all 25 API nodes and 30 edges to
  the synthetic fixture and recomputed all metrics/deltas from saved IDs. The
  absent TRIGGERS relationship-type warning is disclosed. The owned server was
  stopped and its loopback listener confirmed closed afterward. Generated plans,
  human answer quality and healthy HTTP performance remain incomplete.
- Independent review matched the final graph report's metrics, confidence
  intervals, server settings and q059 example to saved evidence, with no further
  important findings. Dependency pins were aligned to observed core versions;
  a fresh environment installation remains explicitly untested.
