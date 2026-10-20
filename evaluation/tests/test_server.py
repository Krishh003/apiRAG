import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evaluation.server import create_app


class ServerTests(unittest.TestCase):
    def test_missing_process_key_does_not_fall_back_to_local_dotenv(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True), patch('dotenv.load_dotenv') as loader:
            app = create_app(Path(directory), retrieval='bm25')

            async def start():
                async with app.router.lifespan_context(app):
                    pass

            with self.assertRaisesRegex(ValueError, 'GEMINI_API_KEY'):
                asyncio.run(start())
            loader.assert_not_called()

    def test_real_query_route_uses_isolated_fixture_without_api_calls(self):
        from fastapi.testclient import TestClient
        from models import QueryResponse

        classifier = SimpleNamespace(classify=lambda question: ('lookup', 'test'))
        handler = SimpleNamespace(handle=lambda *args, **kwargs: QueryResponse(answer='fixture answer', query_type='lookup'))
        handlers = dict.fromkeys(('lookup', 'planning', 'advisory', 'comparison'), handler)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'GEMINI_API_KEY': 'TEST_PLACEHOLDER'}), patch('evaluation.server.build_components', return_value=(classifier, handlers)):
            app = create_app(Path(directory), retrieval='bm25')
            with TestClient(app) as client:
                response = client.post('/api/query', json={'question': 'fixture question'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['answer'], 'fixture answer')
                self.assertEqual(client.post('/admin/scrape', json={}).status_code, 404)
            self.assertTrue((Path(directory) / 'requests.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
