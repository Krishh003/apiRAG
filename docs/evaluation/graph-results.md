# Graph context ablation

The isolated experiment completed 12 synthetic planning queries with the real
`GraphStore.find_apis_for_goal`. Adding graph-first context did not improve this
control. These results measure retrieved source coverage and ordering, not
generated plans or the complete production planning handler.

Evidence: [predictions](results/graph-01/graph_predictions.jsonl),
[metrics and environment](results/graph-01/graph_summary.json),
[server configuration](results/graph-01/execution.json), and
[ingestion/rescoring checks](results/graph-01/validation.json).

| Context configuration | Recall@1 | Recall@5 | MRR@10 | nDCG@10 |
|---|---:|---:|---:|---:|
| Hybrid + cross-encoder, no graph | 0.4097 | 1.0000 | 1.0000 | 0.9764 |
| Graph first, then same vector results | 0.0486 | 0.5417 | 0.3500 | 0.4701 |

Both contexts have a maximum of eight unique documents. MRR/nDCG retain the
cutoff ten definition but can only see the eight supplied documents. Recall@1
is macro document recall; multi-source questions cannot attain 1.0 at rank one.
Recall@5 measures the first five positions, not full eight-document coverage.

| Graph minus no-graph baseline | Mean delta | Paired 95% CI |
|---|---:|---|
| Recall@5 | -0.4583 | [-0.6528, -0.2639] |
| MRR@10 | -0.6500 | [-0.8098, -0.4514] |
| nDCG@10 | -0.5063 | [-0.6865, -0.3197] |

Intervals use 2,000 query-bootstrap samples, seed 20261020, with 12 paired
questions. They are exploratory, unadjusted, and do not represent production
sampling or independent annotation.

The deterministic fallback takes the first five non-stopword query tokens.
Common words such as `and` survive that production fallback. Graph matching
uses OR conditions and an unordered `LIMIT 8`; graph sources precede vector
sources in this control. Together these can displace relevant vector results.
For example, q059's graph-first context contains no SandboxMetrics source,
while its vector context starts with the expected event operations. No query
or label was changed to improve this outcome. The production handler's LLM
keyword extraction could behave differently and remains untested here.

## Traversal performance

| Stage | Samples | p50 ms | p95 ms |
|---|---:|---:|---:|
| Neo4j goal traversal | 12 | 15.848 | 571.230 |

The first traversal took 837.318 ms and is included. This is a fresh server and
database, timed after ingestion, with no separate traversal warmup. Later queries
can reuse connections, query plans and database caches. The OS cache was not
flushed. The one-time graph ingestion took 4,329.118 ms. These small-sample
timings exclude dense retrieval, reranking, Gemini, HTTP and plan generation;
they are not sustained-load estimates.

The run used Neo4j Community 2026.09.0, Java 25, Cypher 5, a 256 MiB initial /
512 MiB maximum heap and 128 MiB page cache. The Python driver was 5.27.0.
Local models used the same pinned BGE/MiniLM snapshots as the learned retrieval
run, CPU with four PyTorch threads. Hardware is the same i7-13650HX / Windows 11
machine described in [methods](README.md).

The initially empty database was verified to contain exactly the fixture's 25
API nodes and 30 relationships after ingestion. Only `PRECEDES` and `REQUIRES`
edges exist in this fixture. Neo4j warned about the absent `TRIGGERS` type used
in the production traversal; this was a notification, not a query failure.
TRIGGERS traversal behavior is therefore not covered. Node/edge verification and
all aggregate metrics were recomputed independently from saved IDs and qrels.
The dedicated server was stopped afterward and its loopback port confirmed closed.

## Reproduction

Any dedicated, empty compatible Neo4j instance can run the existing harness.
The recorded run used a portable Windows archive to avoid an unresponsive
Docker engine. It did not connect to the repository's configured production
Neo4j or use its credentials.

Download and verify the recorded archive in an ignored cache directory:

```powershell
$archive = 'evaluation/cache/neo4j-community-2026.09.0-windows.zip'
Invoke-WebRequest -Uri 'https://dist.neo4j.org/neo4j-community-2026.09.0-windows.zip' -OutFile $archive
$expected = '020929aded4ba31a3b111918f4a4c85aa4dfb55a866d4bb8f6e593878335626e'
if ((Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'Archive checksum mismatch' }
Expand-Archive -LiteralPath $archive -DestinationPath evaluation/cache/graph-reproduction
```

Use a new extraction for each benchmark: the runner refuses a nonempty database.
In its `conf/neo4j.conf`, replace conflicting active settings and add these once:

```properties
db.query.default_language=CYPHER_5
server.default_listen_address=127.0.0.1
server.bolt.listen_address=127.0.0.1:17687
server.bolt.advertised_address=127.0.0.1:17687
server.http.enabled=false
server.https.enabled=false
dbms.security.auth_enabled=false
server.memory.heap.initial_size=256m
server.memory.heap.max_size=512m
server.memory.pagecache.size=128m
dbms.usage_report.enabled=false
```

Authentication is disabled only for this disposable synthetic instance bound to
loopback. For other servers use actual evaluation credentials in environment
variables. In the server terminal:

```powershell
$env:JAVA_HOME = 'C:/Program Files/Java/jdk-25'
$env:NEO4J_HOME = (Resolve-Path 'evaluation/cache/graph-reproduction/neo4j-community-2026.09.0').Path
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$env:NEO4J_HOME/bin/neo4j.ps1" console
```

After the server reports `Started`, in a second terminal use the dependency and
weight-cache setup from [methods](README.md), then:

```powershell
$env:EVAL_NEO4J_URI = 'bolt://127.0.0.1:17687'
$env:EVAL_NEO4J_USER = 'neo4j'
$env:EVAL_NEO4J_PASSWORD = 'UNUSED_LOCAL_AUTH_DISABLED'
$env:EVAL_EMBEDDING_REVISION = 'd4aa6901d3a41ba39fb536a557fa166f842b0e09'
$env:EVAL_RERANKER_REVISION = '233902d25c440f23af6f7d6e94d2946bac0bee0a'
$env:OMP_NUM_THREADS = '4'
$env:MKL_NUM_THREADS = '4'
$env:PYTHONHASHSEED = '0'
python -S -m evaluation.performance graph --isolated-synthetic-server --output evaluation/runs/graph-reproduction
```

`-S` is needed only for the recorded machine's reused `PYTHONPATH` workaround;
use a fresh virtual environment's interpreter normally. Stop the disposable
server with Ctrl+C after collecting results. An unordered graph query and a
different Neo4j version can change selected sources, so retain each run's raw IDs.
