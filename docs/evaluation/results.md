# Offline evaluation results

Generated from saved predictions and frozen synthetic qrels. These are retrieval results, not answer correctness.

Documents: 25; queries: 100; retrieval-labeled: 87.

| Configuration | Recall@1 | Recall@5 | MRR@10 | nDCG@10 |
|---|---:|---:|---:|---:|
| bm25 | 0.4377 [0.3544, 0.5211] | 0.9531 [0.9080, 0.9885] | 0.7541 [0.6897, 0.8172] | 0.8034 [0.7560, 0.8473] |

Brackets: 95% query-bootstrap percentile intervals (2000 resamples, seed 20261020).
Repeated runs are reported separately; repeated queries are not pooled as independent evidence.

## Paired differences

| Treatment minus baseline | Metric | Mean delta | 95% CI |
|---|---|---:|---|

Intervals include query sampling uncertainty only; synthetic authoring bias and corpus mismatch are not captured.

## Warm local performance

| Stage | Samples | p50 ms | p95 ms |
|---|---:|---:|---:|
| bm25 | 300 | 0.815 | 3.638 |

Local bm25 concurrency: 12 requests, 2 workers; failures 0/12 (0.0%); p50 0.668 ms, p95 3.189 ms.
This is a small thread-pool retrieval test; it excludes HTTP, Gemini and event-loop contention.

## Experiment status

| Stage | Status | Attempts | Failures | Reason |
|---|---|---:|---:|---|
| dense | incomplete | 0 | 0 | OSError |
| hybrid | incomplete | 0 | 0 | OSError |
| reranked | incomplete | 0 | 0 | blocked by dense initialization failure |
| graph | incomplete | 0 | 0 | not requested; use the optional dedicated runner |
| generation | incomplete | 0 | 0 | not requested; use the optional dedicated runner |
| http_end_to_end | incomplete | 0 | 0 | not requested; use the optional dedicated runner |
| bm25 | complete | 300 | 0 |  |

See [methods and limitations](README.md), [repository audit](audit.md), and [human review](human-review.md).

![Retrieval metrics](retrieval.png)

![Warm stage latency](latency.png)
