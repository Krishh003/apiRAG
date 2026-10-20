# Measurement-supported resume bullets

- Built a reproducible API retrieval evaluation suite with 100 labeled synthetic
  questions across eight categories, 25 endpoint documents, and four query modes.
- Benchmarked four retrieval configurations across three passes (1,200 saved
  predictions); measured dense MRR@10 of 0.9713 versus hybrid/RRF 0.8860 over
  87 answerable synthetic questions, exposing a regression rather than assuming
  added architecture improved quality.
- Measured a cross-encoder reranking gain from hybrid MRR@10 0.8860 to 0.9636
  (+0.0776; paired 95% bootstrap CI +0.0268 to +0.1312), with reranker-only
  CPU latency p50 289.826 ms and p95 429.680 ms across 300 samples.
- Tested 12 local hybrid requests with two workers and zero observed failures;
  measured p50 230.491 ms and p95 368.915 ms, keeping local retrieval separate
  from quota-limited generation and HTTP diagnostics.

Evidence: [results](results.md) and `results/learned-03/`. The bootstrap unit is the
question, not the three repeats; say "three passes" rather than "261 independent
questions." These bullets describe a synthetic benchmark, not customer impact.
Reranking did not exceed dense's observed score. Do not claim improved hybrid
retrieval, generated-answer correctness, graph planning, production throughput
or reduced model cost from these measurements.
