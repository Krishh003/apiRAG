"""Optional isolated Neo4j ablation and bounded loopback HTTP requests."""

import argparse
import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

from evaluation.backends import ProductionBackend, timed
from evaluation.dataset import fingerprints, load_dataset, write_jsonl
from evaluation.metrics import aggregate, latency_summary, paired_delta, retrieval_metrics
from evaluation.run import environment, save_json


def validate_local_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Use an HTTP loopback origin without credentials, path or query')
    return url.rstrip('/')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_test(url, output, requests=8, workers=2):
    url = validate_local_url(url)
    if not 1 <= requests <= 12 or not 1 <= workers <= 2:
        raise ValueError('HTTP experiment limited to 12 requests and 2 workers')
    _, questions = load_dataset()

    def request(index):
        payload = json.dumps({'question': questions[index]['question']}).encode()
        req = Request(url + '/api/query', data=payload, headers={'Content-Type': 'application/json'})
        # Disable proxies and redirects so loopback cannot become a remote load test.
        opener = build_opener(ProxyHandler({}), NoRedirect())
        error, response = None, None

        def send():
            with opener.open(req, timeout=90) as result:
                return json.load(result)

        start = time.perf_counter_ns()
        try:
            response = send()
            if not isinstance(response, dict):
                raise ValueError('Expected JSON object response')
            answer = response.get('answer', '')
            if not answer or 'ran into an error' in answer.lower() or 'knowledge base is empty' in answer.lower():
                error = 'application_failure'
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            error = type(exc).__name__
        return {'request': index, 'query_id': questions[index]['id'],
                'ms': (time.perf_counter_ns() - start) / 1_000_000, 'error': error,
                'query_type': response.get('query_type') if isinstance(response, dict) else None}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(request, range(requests)))
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / 'http_samples.jsonl', rows)
    save_json(output / 'http_summary.json', {**latency_summary([r['ms'] for r in rows]),
        'workers': workers, 'failures': sum(bool(r['error']) for r in rows),
        'failure_rate': sum(bool(r['error']) for r in rows) / requests,
        'scope': 'HTTP end-to-end; application model calls included; no stage attribution',
        'cache': 'operator must record server warm/cold state separately', 'environment': environment()})


def graph_test(output):
    from neo4j import GraphDatabase

    from models import APIEntry
    from retrieval.graph_store import GraphStore

    uri, user, password = (os.environ.get('EVAL_NEO4J_' + key) for key in ('URI', 'USER', 'PASSWORD'))
    if not all((uri, user, password)):
        raise ValueError('Set EVAL_NEO4J_URI, EVAL_NEO4J_USER, EVAL_NEO4J_PASSWORD for a disposable empty server')
    # Never connect to .env's NEO4J_* settings. Refuse any existing nodes.
    with GraphDatabase.driver(uri, auth=(user, password), connection_timeout=10) as driver:
        with driver.session() as session:
            if session.run('MATCH (n) RETURN count(n) AS n').single()['n'] != 0:
                raise ValueError('Graph benchmark refuses nonempty databases')
    docs, questions = load_dataset()
    graph = GraphStore(uri, user, password)
    output.mkdir(parents=True, exist_ok=True)
    try:
        _, setup_ms = timed(graph.upsert_entries, [APIEntry(**doc['entry']) for doc in docs])
        with tempfile.TemporaryDirectory(prefix='apirag-graph-evaluation-') as temporary:
            backend = ProductionBackend(docs, temporary)
            backend.load_reranker()
            by_name = {doc['entry']['name']: doc['id'] for doc in docs}
            rows, baseline, treatment = [], [], []
            for q in questions:
                if q['mode'] != 'planning':
                    continue
                stopwords = {'how', 'do', 'i', 'we', 'the', 'a', 'an', 'to', 'what', 'api', 'call', 'calls', 'need', 'get', 'make', 'use'}
                keywords = [w for w in q['question'].lower().split() if w not in stopwords][:5]
                # Deterministic production fallback keywords, no reference-derived seed IDs.
                related, elapsed = timed(graph.find_apis_for_goal, goal_keywords=keywords)
                vector = backend.rerank(q['question'], backend.hybrid(q['question'], depth=10), depth=8)
                without = [r['id'] for r in vector]
                with_graph = list(dict.fromkeys([by_name[r['name']] for r in related] + without))[:8]
                baseline.append(retrieval_metrics(without, q['relevance']))
                treatment.append(retrieval_metrics(with_graph, q['relevance']))
                rows.append({'query_id': q['id'], 'keywords': keywords, 'graph_ms': elapsed,
                             'without_graph': without, 'with_graph': with_graph})
            write_jsonl(output / 'graph_predictions.jsonl', rows)
            save_json(output / 'graph_summary.json', {'n': len(rows), 'graph_ingestion_ms': setup_ms,
                'latency': latency_summary([r['graph_ms'] for r in rows]),
                'without_graph': aggregate(baseline), 'with_graph': aggregate(treatment),
                'paired_delta': paired_delta(baseline, treatment), 'sha256': fingerprints(),
                'environment': environment(), 'budget': 8,
                'scope': 'source coverage, not generated plan correctness; graph-first equal-budget context ablation',
                'limitations': 'Deterministic fallback keywords, no Gemini extraction; Neo4j LIMIT order unspecified; database left intact for inspection.'})
    finally:
        graph.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['http', 'graph'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--requests', type=int, default=8)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--isolated-synthetic-server', action='store_true', required=True,
                        help='Confirm target is a dedicated synthetic-data evaluation server')
    args = parser.parse_args()
    if args.mode == 'http':
        http_test(args.url, args.output, args.requests, args.workers)
    else:
        graph_test(args.output)


if __name__ == '__main__':
    main()
