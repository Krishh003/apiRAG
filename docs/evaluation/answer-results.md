# Gemini answer and HTTP diagnostics

Run date: 2026-10-20. These runs use **BM25 only**, the original classifier and
four answer handlers, synthetic documents, no cross-encoder, and no graph.
They do not establish hybrid retrieval or reranking quality. No LLM judge was
used, and all human-review fields remain pending.

## Recorded runs

| Run | Questions | Answer texts without application error | Application failures | Notes |
|---|---:|---:|---:|---|
| Initial bounded diagnostic | 12 | 2 | 10 | Request pacing was insufficient for the configured quota |
| Paced BM25 baseline | 12 | 7 | 5 | 15-second per-model interval; stop further calls after quota failure |

These are service diagnostics, not controlled evidence of quality improvement.
The quota window, stochastic responses and successful question subset differ.
Do not compare answer accuracy or latency between these runs as an ablation.
An answer text without an application error has **not** been judged correct.

Evidence is stored under `results/answers-bm25-initial/` and
`results/answers-bm25-paced/`. Counts are calculated from saved `answers.jsonl`
and checked against `answer_summary.json`.

The provider reported zero available Gemini 2.5 Pro quota, five Flash requests
per minute, and a 20-request Flash daily allowance. The daily allowance was
exhausted during the paced run. Further generation requests were stopped.
No replacement model or higher production output limit was used to conceal
these failures. Each benchmark run now suppresses further requests to a model
after its first quota error, and records suppressed calls separately.

## Paced run performance and usage

| Measurement | Samples | p50 | p95 |
|---|---:|---:|---:|
| Actual model API requests, including two provider errors | 16 | 2.759 s | 5.024 s |
| Classifier + handler, including retrieval and client pacing | 12 | 16.253 s | 29.974 s |

The saved call log contains 20 model-call events: 16 actual API requests and
four locally suppressed calls. Two actual requests returned quota errors.
Provider usage was available for 14 responses: 5,405 input tokens, 515 reported
output tokens and 8,908 total tokens. Input plus reported output does not equal
the total; no unreported-token attribution or cost estimate is inferred.

Model aliases and production settings are documented in the audit. Five calls
ended with provider finish reason `MAX_TOKENS`, including short classification
or keyword-extraction calls. Two returned no text. These are not necessarily
HTTP API errors; the existing classifier/keyword fallback behavior is retained.
Source-derived confidence in the lexical control is not calibrated answer quality.

Warm/cold assumptions: BM25 index built once per process; no answer cache;
sequential generation, 15-second per-model pacing, one-second between questions.
Pacing is excluded from model API timers and included in handler timers. These
small, quota-constrained samples do not establish production p95 or capacity.

## Agent spot-checks, not human adjudication

| Question | Observation grounded in the saved answer and synthetic contract |
|---|---|
| q001 | Describes the pending state and `/v1/payments` correctly; omits the HTTP verb listed in the reference facts |
| q063 | Comparison sources omit Create payment; the answer says its details are missing even though that document exists in the corpus |
| q064 | Only Capture payment survives source selection; the answer cannot supply the documented Confirm payment behavior |
| q085 | Ambiguous “Send it.” receives options instead of asking for the missing platform/resource clarification |
| q091 | Explicitly states that the requested Bitcoin settlement endpoint is not documented |
| q096 | Declines to reveal a client secret and states that it is not in the supplied documentation |

These observations cover factual content, source coverage, ambiguity handling,
missing-information abstention and a misleading/secret request. They are an
assistant inspection of six cases, not independently scored ground truth. No
aggregate correctness, grounding or abstention rate is claimed. Human review
remains pending for all 12 questions, including the five application failures.

## HTTP failure diagnostic

The isolated loopback server reused the actual `main.query` endpoint with only
synthetic BM25 context. It did not run production startup, ingestion, admin
routes or a graph connection. Four client requests used two workers. All four
returned HTTP 200, but all four contained application-level quota failures.
The client correctly marked failure rate **4/4**, rather than treating status
200 as a successful answer. Recorded p50 is 951.599 ms and p95 1,876.586 ms;
these are **failure-path timings**, not healthy end-to-end performance.

Evidence: `results/http-bm25-quota/` contains client samples, server requests,
model-call events and server configuration. Global model events are not
attributed to individual concurrent requests. Server warm/cold state: initialized
BM25 index, no prior successful generation in that server, provider quota already
exhausted. A separate sandbox-blocked connection probe is kept private and is
excluded from application performance evidence. The benchmark server was stopped.

## Reproduce after restoring provider quota

Existing production model names and output settings remain unchanged:

```powershell
python -m evaluation.answers generate --env-file .env --retrieval bm25 --limit 12 --api-interval-seconds 15 --output evaluation/private/answers-next
```

Run the isolated HTTP server in one terminal, then the small client test in another:

```powershell
python -m evaluation.server --env-file .env --retrieval bm25 --port 18081 --api-interval-seconds 15 --output evaluation/private/http-server-next
python -m evaluation.performance http --isolated-synthetic-server --url http://127.0.0.1:18081 --requests 4 --workers 2 --output evaluation/private/http-next
```

Do not run generation and HTTP tests simultaneously against a shared quota.
Use a fresh output path for each run. Only the explicit `--env-file` option loads
credentials; no secret value is written to the result files. The initial service
diagnostics loaded the existing local key into process memory, unlike the earlier
offline retrieval run, which did not read `.env`.

Reproducibility limit: these service diagnostics used uncommitted evaluator
extensions. Their original manifests hash production retrieval/model files but
do not fully identify the evaluator and handler code loaded at the time. New
runs now hash the evaluator, HTTP route and all query modules, and model-call
records include generation settings plus a system-instruction hash. This cannot
retroactively make the earlier manifests complete. Provider alias versions and
stochastic behavior also limit exact answer reproduction.
