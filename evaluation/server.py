"""Loopback-only benchmark server using the existing query route and synthetic KB."""

import argparse
import os
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI

from evaluation.answers import BM25AnswerBackend, build_components
from evaluation.backends import ProductionBackend
from evaluation.dataset import fingerprints, load_dataset, write_jsonl
from evaluation.run import environment, save_json


def create_app(output, retrieval='production', api_interval_seconds=15):
    if retrieval not in ('production', 'bm25'):
        raise ValueError('Choose production or bm25 retrieval')
    output = Path(output)
    calls, requests = [], []

    @asynccontextmanager
    async def lifespan(app):
        key = os.environ.get('GEMINI_API_KEY')
        if not key:
            raise ValueError('GEMINI_API_KEY is required')
        # Isolate main's automatic dotenv loading as well as its lifespan.
        from dotenv import load_dotenv

        with patch('dotenv.load_dotenv', return_value=False):
            import main
        main.load_dotenv = load_dotenv
        output.mkdir(parents=True, exist_ok=True)
        if (output / 'requests.jsonl').exists():
            raise ValueError('Use a fresh output directory')
        docs, _ = load_dataset()
        with tempfile.TemporaryDirectory(prefix='apirag-http-evaluation-') as temporary:
            backend = BM25AnswerBackend(docs) if retrieval == 'bm25' else ProductionBackend(docs, temporary)
            if retrieval == 'production':
                backend.load_reranker()
            classifier, handlers = build_components(backend, key, calls, api_interval_seconds=api_interval_seconds)
            values = {'vector_store': backend.store, 'classifier': classifier,
                      **{mode + '_handler': handler for mode, handler in handlers.items()}}
            original = {name: getattr(main, name) for name in values}
            for name, value in values.items():
                setattr(main, name, value)
            app.add_api_route('/api/query', main.query, methods=['POST'])
            save_json(output / 'server_config.json', {
                'retrieval_config': retrieval, 'graph': 'disabled', 'documents': len(docs),
                'sha256': fingerprints(), 'environment': environment(),
                'api_interval_seconds': api_interval_seconds,
                'scope': 'actual main.query route; synthetic KB; no production startup, ingestion or admin routes'})
            try:
                yield
            finally:
                write_jsonl(output / 'model_calls.jsonl', calls)
                for name, value in original.items():
                    setattr(main, name, value)

    app = FastAPI(title='Synthetic API RAG benchmark only', lifespan=lifespan)

    @app.middleware('http')
    async def record_request(request, call_next):
        start = time.perf_counter_ns()
        response = await call_next(request)
        requests.append({'path': request.url.path, 'status': response.status_code,
                         'ms': (time.perf_counter_ns() - start) / 1_000_000})
        write_jsonl(output / 'requests.jsonl', requests)
        write_jsonl(output / 'model_calls.jsonl', calls)
        return response

    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--retrieval', choices=['production', 'bm25'], default='production')
    parser.add_argument('--port', type=int, default=18081)
    parser.add_argument('--api-interval-seconds', type=float, default=15)
    parser.add_argument('--env-file', type=Path, help='Explicitly load credentials into this process only')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Use an unprivileged TCP port')
    if args.env_file:
        from dotenv import load_dotenv

        load_dotenv(args.env_file)
    uvicorn.run(create_app(args.output, args.retrieval, args.api_interval_seconds), host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
