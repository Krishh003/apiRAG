# Evaluation methods and reproduction

This suite measures an original synthetic fixture, without reading the production
knowledge base. Start with the [audit](audit.md), [generated results](results.md),
[annotation schema](../../evaluation/data/question.schema.json), and
[answer review protocol](human-review.md).

## Verified versus incomplete

The completed run in `results/learned-03/` executes all four controls on 100
questions and 25 synthetic endpoint documents three times: 1,200 predictions,
zero retrieval errors. Ranking metrics cover the 87 answerable questions.
Thirteen ambiguous/absent/adversarial requests have no relevant documents and
are excluded from ranking aggregates, not counted as perfect answers.

Dense MRR@10 was 0.9713, BM25 0.7541, hybrid/RRF 0.8860 and reranked hybrid
0.9636. Hybrid minus dense MRR was -0.0852 (paired 95% CI -0.1360 to -0.0393);
reranked minus hybrid was +0.0776 (CI +0.0268 to +0.1312). Thus this fixture
supports a reranking gain over hybrid, but does not support adding BM25/RRF to
improve the dense baseline. Dense, hybrid and reranked Recall@5 all saturate at
1.0. These are authored synthetic labels, not production quality estimates.
All four aggregate metric values were identical across the three passes.

Earlier attempts remain inspectable: `results/offline/` had no cached weights;
`results/learned/` hit an incompatible system Torchvision import;
`results/learned-02/` was interrupted while writing a checkpoint after 772 saved
predictions. They are excluded from the completed run's aggregates. Model weights
were downloaded and checksum-verified before running `learned-03` offline.

A [BM25 Gemini baseline and HTTP diagnostic](answer-results.md) have now
run: seven answer texts from 12 questions, with five application failures under
provider quotas. Model API timing and token usage are recorded; human quality
scores and costs remain unreported. Four HTTP requests all reached handled quota
failures, so healthy-service HTTP performance remains incomplete. Graph traversal
also remains incomplete. The small offline BM25 concurrency experiment tests
local retrieval only. The completed learned run also tested 12 hybrid requests
with two workers: zero observed failures, p50 230.491 ms and p95 368.915 ms.

## Setup

Use Python 3.10 on Windows with PowerShell. A fresh environment is recommended:

```powershell
python -m venv evaluation/cache/venv
& ./evaluation/cache/venv/Scripts/Activate.ps1
python -m pip install -r requirements.txt -r evaluation/requirements.txt
python -m evaluation.dataset
python -m unittest discover -s evaluation/tests -v
```

The task environment's `.venv` interpreter points to a missing Miniconda install.
The recorded full probe instead used the existing Python 3.10-compatible project
libraries through system Python:

```powershell
$env:PYTHONPATH = (Resolve-Path '.venv/Lib/site-packages').Path
$env:HF_HOME = Join-Path (Get-Location).Path 'evaluation/cache/huggingface'
$env:PYTHONHASHSEED = '0'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
python -S -m evaluation.run --output evaluation/runs/offline-reproduction --repeats 3
```

This workaround is local to the shell. It does not repair or mutate the app
environment. Actual package versions and source SHA256 hashes are recorded in
`results/learned-03/environment.json`; do not assume that a base Git SHA alone
captures the user's pre-existing staged retrieval modifications.

The local learned run uses `python -S` to exclude system site packages while
retaining the explicit project `PYTHONPATH`. Without this isolation, the system's
Torchvision conflicts with the project's CPU PyTorch (`torchvision::nms` missing).
The failed attempt is retained in `results/learned/`. A fresh, consistently
installed virtual environment should use its own interpreter normally.

For BM25 and standard-library harness tests, weights and credentials are unnecessary:

```powershell
python -m pip install numpy==2.2.6 rank_bm25==0.2.2
$env:PYTHONHASHSEED = '0'
python -m evaluation.run --bm25-only --output evaluation/runs/bm25-01 --repeats 3
```

## Run all learned retrieval controls

Download the BGE and cross-encoder weights on a machine with sufficient network
access, then run without offline variables for the initial download:

```powershell
Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue
Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
$env:ANONYMIZED_TELEMETRY = 'False'
$env:PYTHONHASHSEED = '0'
python -m evaluation.run --output evaluation/runs/learned-01 --repeats 3
```

No Gemini credentials are needed. All learned controls use the production
VectorStore and Reranker in a new temporary Chroma directory. No ingestion,
app startup or scheduler runs. The standalone BM25 adapter uses the production
serializer's exact fields and tokenizer; integration tests assert parity.

| Configuration | Candidate control | Output |
|---|---|---|
| Dense | Chroma cosine, BAAI/bge-large-en-v1.5, CPU, depth 20 | top 10 |
| BM25 | rank_bm25 BM25Okapi defaults, lowercase whitespace, positive scores, depth 20 | top 10 |
| Hybrid | production dense + BM25, both depth 20, RRF k=60 | top 10 |
| Reranked | same hybrid top 10, production MiniLM cross-encoder | top 10 |

All configurations see the same frozen documents, queries and labels. No filters
are applied. The corpus is small (25 documents), so branch depth 20 is generous.
Reranking cannot improve Recall@10 because it only reorders the same ten sources.
It can improve or worsen their positions. Production's missing-rank contribution,
four-decimal score ties and 512-character reranker truncation are preserved;
no canonical-RRF or longer-context improvement is smuggled into this benchmark.
This is endpoint retrieval; it does not reproduce per-concept comparison
retrieval, automatic routing or graph-first planning at this stage.

The model manifest records resolved revisions, actual devices, weight hashes and
tokenizer vocabulary hashes when models load. To reproduce a completed learned
run, use the revisions from that manifest:

```powershell
$env:EVAL_EMBEDDING_REVISION = 'd4aa6901d3a41ba39fb536a557fa166f842b0e09'
$env:EVAL_RERANKER_REVISION = '233902d25c440f23af6f7d6e94d2946bac0bee0a'
python -m evaluation.run --output evaluation/runs/learned-pinned --repeats 3
```

No loaded model manifest is claimed for failed setup runs. Package pins
alone do not freeze remote weights. Existing production tie ordering may still
vary with Chroma/platform versions; retain predictions for every run.

## Saved evidence and metric definitions

Each run writes `config.json`, `environment.json`, `predictions.jsonl`,
`timings.jsonl`, `errors.jsonl` and `summary.json`. Per-query predictions include
configuration, repeat, stable IDs, scores and errors. Empty prediction lists on
answerable items score zero. Unanswerable items score null and are excluded.
Repeated requests are not pooled to inflate query-bootstrap sample size.

- Recall@k: number of unique relevant IDs retrieved in first k / all relevant IDs.
  This is macro document recall, **not hit rate**; multi-source questions can have
  Recall@1 below 1 even with a relevant first result.
- MRR@10: reciprocal of the first relevant rank within ten; zero if no hit.
- nDCG@10: discounted gain `(2^grade - 1)/log2(rank+1)` normalized by ideal gain.
  v1 labels are binary-relevance grade 2; graded labels are supported by tests.
- CIs: 2000 percentile bootstrap resamples of queries, seed 20261020. Compare
  treatments using paired per-query differences with explicit dense or hybrid
  baselines. These intervals do not capture annotation bias or production drift.
  Intervals are exploratory and are not adjusted for multiple comparisons.

Recompute scores without loading models or calling an API:

```powershell
python -m evaluation.run --score-only docs/evaluation/results/learned-03/predictions.jsonl --output evaluation/runs/rescore
python -m evaluation.report --run docs/evaluation/results/learned-03 --output docs/evaluation
python -m evaluation.answers prepare --predictions docs/evaluation/results/offline/predictions.jsonl --config bm25 --output evaluation/private/review.jsonl
```

The report generator checks its aggregates against saved predictions before
rendering tables/plots. Predicted IDs and qrels are the metric inputs, not hand
typed summary numbers. Failed requests score zero and are counted separately.
Stage status distinguishes complete, partial, failed and incomplete experiments.

## Performance methodology

Timers use `perf_counter_ns`. Separate cold model/index setup and first queries
from warm requests. Dense includes query embedding and Chroma search; BM25 is
keyword retrieval; hybrid includes both branches, fusion and metadata fetch.
`fusion_kernel` measures just the RRF arithmetic on cached branch rankings;
it is not additional end-to-end work and excludes sorting/fetching.
`reranker_only` measures rescoring/reordering, excluding retrieval. Latency
aggregates include attempted measured requests, including failed attempts;
setup/warmup failures remain errors rather than latency samples.
"Cold setup" means a new Python process and temporary index with weights already
on disk. The OS page cache was not flushed; a model-loading diagnostic preceded
the learned run. It is not a clean-boot or cold-download measurement.

Queries are shuffled deterministically per repeat. Run order is BM25, dense,
hybrid, reranked for each query; CPU/cache carryover and OS background load can
affect timings. Four PyTorch threads are set for learned controls. Embeddings
are CPU; the existing reranker's selected device is recorded in the manifest.
No model API latency is mixed into offline timings.

Hardware observed locally: Intel Core i7-13650HX (14 cores, 20 logical processors),
16,780,546,048 bytes RAM; Windows 11 build 26200. The runtime reports an NT
`Windows-10` platform string. See the run's JSON for actual Python/package
versions. No GPU inference was measured.

The default local concurrency test has 12 retrieval requests, 2 workers, bounded
at 32 requests/4 workers. It records failures, p50/p95, samples and wall time;
per-request timers exclude queue wait. This sample is too small to establish
production reliability or sustained throughput.

Optional HTTP test, only against a separately prepared **synthetic**, loopback
app (maximum 12 requests/2 workers; no redirect or proxy forwarding):

```powershell
python -m evaluation.performance http --isolated-synthetic-server --url http://127.0.0.1:8000 --requests 8 --workers 2 --output evaluation/private/http-01
```

Use `python -m evaluation.server --env-file .env --retrieval bm25 --output evaluation/private/http-server-next`
to start a loopback-only server using the actual query route and the synthetic
fixture, with no production startup or ingestion. Record app/server/model
configuration, index hashes and warm/cold state alongside the run. This command
may incur Gemini calls. The recorded HTTP run is a quota-failure diagnostic;
healthy-service performance remains incomplete.

Optional graph experiment requires `EVAL_NEO4J_URI`, `EVAL_NEO4J_USER`, and
`EVAL_NEO4J_PASSWORD` in the process environment for a disposable empty instance:

```powershell
python -m evaluation.performance graph --isolated-synthetic-server --output evaluation/private/graph-01
```

It refuses any existing nodes, imports only synthetic entries, uses the real
GraphStore goal traversal, records traversal latency and compares source coverage
with/without graph at equal context budget 8. Deterministic production fallback
keywords avoid Gemini extraction and do not use labels. It is a controlled
context-coverage ablation, not actual generated-plan correctness or the complete
planning handler (which reranks six vector sources). It leaves its disposable
database intact for inspection; never use a shared default database. Current
graph latency and quality are incomplete.

Optional answer generation, model API timing/usage and manual review are covered
in [human-review.md](human-review.md). Prices default to null. No LLM judge is
used; do not present future judge scores as ground truth.

## Limitations and confidentiality review

The fixture is original synthetic data with authored labels, recurring question
forms and six fictional platforms. It is not a production quality estimate.
Source recall is not factual correctness, abstention, workflow ordering or
unsupported-claim detection. Independent annotation and answer review remain
pending; no human agreement statistic is claimed. General advisory knowledge
must be distinguished from KB grounding. Neo4j and full Gemini
experiments remain incomplete as listed above.

No production source/UI files changed. Unit/integration tests cover metrics,
qrel integrity, serializer/BM25 parity, reranker truncation, empty/OOV queries,
failure evidence, review validation and loopback load-test restrictions.
Live UI regressions were not tested. Service-backed diagnostics are limited to
the Gemini/HTTP evidence described above.

Review of new files found only synthetic API contracts, evaluation code and
machine/package metadata. `.env` is ignored; the offline run did not read it.
The service diagnostics loaded its key into process memory without displaying
or saving it. Existing PDFs,
internal templates, user-staged changes and live Chroma data are excluded.
The owner confirmed that the previous proprietary/internal-use notice was
incorrect and authorized publication of the benchmark changes. That notice has
been removed. The benchmark commit excludes the user's pre-existing staged work.
