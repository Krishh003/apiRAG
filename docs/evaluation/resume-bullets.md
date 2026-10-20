# Measurement-supported resume bullets

- Built a reproducible API retrieval evaluation suite with 100 labeled synthetic
  questions across eight categories, 25 endpoint documents, and four query modes.
- Established a BM25 baseline with Recall@5 of 0.9531 and MRR@10 of 0.7541 over
  87 answerable questions; saved per-query predictions and computed seeded 95%
  bootstrap intervals across three repeated evaluation passes.
- Added a bounded two-worker retrieval test: 12 local BM25 requests, zero observed
  failures; retained latency samples and separated retrieval from unrun generation
  and HTTP experiments.

Evidence: [results](results.md) and `results/offline/`. The bootstrap unit is the
question, not the three repeats; say "three passes" rather than "261 independent
questions." These bullets describe a synthetic benchmark, not customer impact.
Do not claim improved hybrid retrieval, reranking accuracy, graph planning,
production throughput or reduced model cost until those experiments run.
