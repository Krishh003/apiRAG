"""Matched retrieval ablations, saved predictions and local concurrency test."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import random
import subprocess
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from evaluation.backends import BM25Backend, ProductionBackend, production_rrf, timed
from evaluation.dataset import fingerprints, load_dataset, read_jsonl, write_jsonl
from evaluation.metrics import aggregate, latency_summary, paired_delta, retrieval_metrics


def environment():
    packages = {}
    for name in ('numpy', 'torch', 'sentence-transformers', 'transformers', 'tokenizers',
                 'chromadb', 'rank_bm25', 'neo4j', 'google-generativeai', 'matplotlib'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    root = Path(__file__).resolve().parents[1]
    source_names = ['retrieval/vector_store.py', 'retrieval/reranker.py',
                    'retrieval/graph_store.py', 'models.py', 'main.py']
    source_names += [p.relative_to(root).as_posix() for p in sorted((root / 'query').glob('*.py'))]
    source_names += ['evaluation/' + name + '.py' for name in
                     ('answers', 'server', 'run', 'backends', 'dataset', 'metrics', 'performance')]
    source_hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in source_names}
    info = {'python': platform.python_version(), 'os': platform.platform(),
            'cpu': platform.processor(), 'logical_cpus': os.cpu_count(), 'packages': packages}
    info['source_sha256'] = source_hashes
    if os.name == 'nt':
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
                info['cpu'] = winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
        except OSError:
            pass
    try:
        import psutil

        info['ram_bytes'] = psutil.virtual_memory().total
    except ImportError:
        info['ram_bytes'] = None
    try:
        info['git_head'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        info['git_head'] = None
    return info


def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def score_predictions(rows, questions):
    labels = {q['id']: q for q in questions}
    grouped = defaultdict(list)
    seen = set()
    for row in rows:
        key = (row['config'], row['repeat'], row['query_id'])
        if key in seen or row['query_id'] not in labels:
            raise ValueError('Duplicate or unknown query prediction')
        seen.add(key)
        grouped[(row['config'], row['repeat'])].append(row)
    for group in grouped.values():
        if {r['query_id'] for r in group} != set(labels):
            raise ValueError('Incomplete query coverage; failures must be explicit empty predictions')
    configs = sorted({key[0] for key in grouped})
    retrieval, comparisons = {}, {}
    first_metrics = {}
    for config in configs:
        repeat_ids = sorted(repeat for name, repeat in grouped if name == config)
        metrics_by_repeat = {}
        for repeat in repeat_ids:
            metrics_by_repeat[repeat] = {
                r['query_id']: retrieval_metrics(r['predicted_ids'], labels[r['query_id']]['relevance'])
                for r in grouped[(config, repeat)]}
        first = metrics_by_repeat[repeat_ids[0]]
        first_metrics[config] = first
        retrieval[config] = {
            'overall': aggregate(list(first.values())),
            'by_category': {category: aggregate([first[q['id']] for q in questions if q['category'] == category])
                            for category in sorted({q['category'] for q in questions})},
            'repeats': {str(repeat): aggregate(list(metrics.values()))
                        for repeat, metrics in metrics_by_repeat.items()},
            'unanswerable_excluded': sum(not q['answerable'] for q in questions),
            'errors': sum(bool(row.get('error')) for repeat in repeat_ids for row in grouped[(config, repeat)]),
        }
    for baseline, treatment in [('dense', 'bm25'), ('dense', 'hybrid'), ('hybrid', 'reranked')]:
        if baseline in first_metrics and treatment in first_metrics:
            ids = sorted(labels)
            comparisons[f'{treatment}_minus_{baseline}'] = paired_delta(
                [first_metrics[baseline][qid] for qid in ids], [first_metrics[treatment][qid] for qid in ids])
    return {'retrieval': retrieval, 'paired_deltas': comparisons}


def concurrency_test(function, questions, requests=12, workers=2):
    if requests < 1 or requests > 32 or workers < 1 or workers > 4:
        raise ValueError('Bounded local test requires 1..32 requests and 1..4 workers')

    def request(index):
        start = time.perf_counter_ns()
        error = None
        try:
            function(questions[index % len(questions)]['question'])
        except (ValueError, RuntimeError, OSError) as exc:
            error = type(exc).__name__
        return {'request': index, 'ms': (time.perf_counter_ns() - start) / 1_000_000, 'error': error}

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(request, range(requests)))
    return {**latency_summary([r['ms'] for r in rows]), 'workers': workers,
            'failures': sum(bool(r['error']) for r in rows),
            'failure_rate': sum(bool(r['error']) for r in rows) / requests,
            'wall_seconds': time.perf_counter() - start, 'samples': rows,
            'scope': 'local retrieval only; no HTTP or model API; warm models/index; queue wait excluded'}


def evaluate(docs, questions, output, bm25_only=False, repeats=1, concurrent_requests=12):
    if repeats < 1:
        raise ValueError('repeats must be positive')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'predictions.jsonl').exists():
        raise ValueError('Use a fresh output directory to preserve previous evidence')
    rows, timings, errors = [], [], []
    stages = {name: {'status': 'incomplete', 'reason': 'not requested; use the optional dedicated runner'}
              for name in ('dense', 'hybrid', 'reranked', 'graph', 'generation', 'http_end_to_end')}
    config = {'sha256': fingerprints(), 'depth': 10, 'branch_depth': 20, 'rrf_k': 60,
              'rrf_missing_rank': 'union_size+1 (production)', 'repeats': repeats,
              'embedding': 'BAAI/bge-large-en-v1.5', 'embedding_device': 'cpu', 'torch_threads': 4,
              'reranker': 'cross-encoder/ms-marco-MiniLM-L-6-v2', 'rerank_chars': 512,
              'requested_embedding_revision': os.getenv('EVAL_EMBEDDING_REVISION'),
              'requested_reranker_revision': os.getenv('EVAL_RERANKER_REVISION'),
              'rerank_max_tokens': 512, 'query_seed': 20261020,
              'bootstrap': {'unit': 'query', 'resamples': 2000, 'seed': 20261020},
              'cache': 'fresh temporary Chroma index; model load/index and first query separate; warm timed requests; no answer cache',
              'hash_seed': os.getenv('PYTHONHASHSEED', 'unset; production tie order may vary')}
    save_json(output / 'config.json', config)
    save_json(output / 'environment.json', environment())
    lexical, cold_bm25 = timed(BM25Backend, docs)
    cold = {'bm25_index_ms': cold_bm25}
    model_manifest = {}
    with tempfile.TemporaryDirectory(prefix='apirag-evaluation-') as temporary:
        backend = None
        if not bm25_only:
            try:
                import torch

                torch.set_num_threads(4)
                torch.manual_seed(20261020)
                backend, cold['dense_model_and_index_ms'] = timed(ProductionBackend, docs, Path(temporary))
                stages['dense'] = stages['hybrid'] = {'status': 'complete'}
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                # Save only error class: external messages can contain credentials/paths.
                errors.append({'stage': 'dense_setup', 'error': type(exc).__name__})
                stages['dense'] = stages['hybrid'] = {'status': 'incomplete', 'reason': type(exc).__name__}
                stages['reranked'] = {'status': 'incomplete', 'reason': 'blocked by dense initialization failure'}
            if backend:
                try:
                    _, cold['reranker_model_ms'] = timed(backend.load_reranker)
                    stages['reranked'] = {'status': 'complete'}
                except (ImportError, OSError, RuntimeError, ValueError) as exc:
                    stages['reranked'] = {'status': 'incomplete', 'reason': type(exc).__name__}
                    errors.append({'stage': 'reranker_setup', 'error': type(exc).__name__})
                try:
                    _, cold['first_dense_query_ms'] = timed(backend.dense, questions[0]['question'])
                    candidates, cold['first_hybrid_query_ms'] = timed(backend.hybrid, questions[0]['question'])
                except (ValueError, RuntimeError, OSError) as exc:
                    errors.append({'stage': 'dense_hybrid_warmup', 'error': type(exc).__name__})
                    for name in ('dense', 'hybrid', 'reranked'):
                        stages[name] = {'status': 'incomplete', 'reason': 'first inference failed: ' + type(exc).__name__}
                    backend = None
                if backend and stages['reranked']['status'] == 'complete':
                    try:
                        _, cold['first_rerank_query_ms'] = timed(backend.rerank, questions[0]['question'], candidates)
                    except (ValueError, RuntimeError, OSError) as exc:
                        errors.append({'stage': 'reranker_warmup', 'error': type(exc).__name__})
                        stages['reranked'] = {'status': 'incomplete', 'reason': 'first inference failed: ' + type(exc).__name__}
                if backend:
                    model_manifest = backend.model_manifest()
        write_jsonl(output / 'errors.jsonl', errors)
        for repeat in range(repeats):
            order = list(questions)
            random.Random(20261020 + repeat).shuffle(order)
            for q in order:
                question, qid = q['question'], q['id']
                dense_results, hybrid_results = [], []
                jobs = [('bm25', lambda: lexical.search(question))]
                if backend:
                    jobs.extend([('dense', lambda: backend.dense(question)),
                                 ('hybrid', lambda: backend.hybrid(question))])
                for name, function in jobs:
                    error, elapsed, results = None, None, []
                    start = time.perf_counter_ns()
                    try:
                        results, elapsed = timed(function)
                    except (ValueError, RuntimeError, OSError) as exc:
                        elapsed = (time.perf_counter_ns() - start) / 1_000_000
                        error = type(exc).__name__
                        errors.append({'query_id': qid, 'repeat': repeat, 'stage': name, 'error': error})
                    if name == 'dense':
                        dense_results = results
                    elif name == 'hybrid':
                        hybrid_results = results
                    rows.append({'query_id': qid, 'config': name, 'repeat': repeat,
                                 'predicted_ids': [r['id'] for r in results[:10]],
                                 'scores': [r.get('score', r.get('rrf_score')) for r in results[:10]],
                                 'error': error})
                    timings.append({'query_id': qid, 'repeat': repeat, 'stage': name, 'ms': elapsed, 'error': error})
                if backend:
                    # Kernel-only RRF on cached branch results; distinct from production
                    # hybrid total, which includes both searches and metadata fetch.
                    lexical_results = lexical.search(question)
                    _, elapsed = timed(production_rrf, [r['id'] for r in dense_results], [r['id'] for r in lexical_results])
                    timings.append({'query_id': qid, 'repeat': repeat, 'stage': 'fusion_kernel', 'ms': elapsed, 'error': None})
                    if stages['reranked']['status'] == 'complete':
                        error, results, elapsed = None, [], None
                        start = time.perf_counter_ns()
                        try:
                            results, elapsed = timed(backend.rerank, question, hybrid_results)
                        except (ValueError, RuntimeError, OSError) as exc:
                            elapsed = (time.perf_counter_ns() - start) / 1_000_000
                            error = type(exc).__name__
                            errors.append({'query_id': qid, 'repeat': repeat, 'stage': 'reranked', 'error': error})
                        hybrid_error = rows[-1]['error']
                        error = error or hybrid_error
                        rows.append({'query_id': qid, 'config': 'reranked', 'repeat': repeat,
                                     'predicted_ids': [r['id'] for r in results],
                                     'scores': [r['rerank_score'] for r in results], 'error': error})
                        timings.append({'query_id': qid, 'repeat': repeat, 'stage': 'reranker_only', 'ms': elapsed, 'error': error})
                if len(rows) % 40 == 0:
                    print(f'Repeat {repeat + 1}: saved {len(rows)} predictions', flush=True)
                # Checkpoint after each query so interrupted experiments remain inspectable.
                write_jsonl(output / 'predictions.jsonl', rows)
                write_jsonl(output / 'timings.jsonl', timings)
                write_jsonl(output / 'errors.jsonl', errors)
        concurrent = concurrency_test(backend.hybrid if backend else lexical.search, questions, requests=concurrent_requests)
        concurrent['configuration'] = 'hybrid' if backend else 'bm25'
    scored = score_predictions(read_jsonl(output / 'predictions.jsonl'), questions)
    stage_times = defaultdict(list)
    for row in timings:
        if row['ms'] is not None:
            stage_times[row['stage']].append(row['ms'])
    for name in {row['config'] for row in rows}:
        attempts = [row for row in rows if row['config'] == name]
        failures = sum(bool(row['error']) for row in attempts)
        stages[name] = {'status': 'complete' if not failures else 'failed' if failures == len(attempts) else 'partial',
                        'attempted': len(attempts), 'failed': failures, 'successful': len(attempts) - failures}
    summary = {**scored, 'created_utc': datetime.now(timezone.utc).isoformat(), 'stages': stages,
               'latencies': {name: latency_summary(values) for name, values in stage_times.items()},
               'cold_setup': cold, 'concurrency': concurrent, 'model_manifest': model_manifest,
               'counts': {'documents': len(docs), 'questions': len(questions), 'answerable': sum(q['answerable'] for q in questions)}}
    save_json(output / 'summary.json', summary)
    write_jsonl(output / 'errors.jsonl', errors)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bm25-only', action='store_true')
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--requests', type=int, default=12)
    parser.add_argument('--score-only', type=Path, help='Recompute metrics from saved prediction file')
    args = parser.parse_args()
    docs, questions = load_dataset()
    if args.score_only:
        args.output.mkdir(parents=True, exist_ok=True)
        save_json(args.output / 'rescored.json', score_predictions(read_jsonl(args.score_only), questions))
    else:
        summary = evaluate(docs, questions, args.output, args.bm25_only, args.repeats, args.requests)
        print(json.dumps({'counts': summary['counts'], 'stages': summary['stages']}, indent=2))


if __name__ == '__main__':
    main()
