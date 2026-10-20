"""Real serialization/BM25/reranker integration; learned weights not required."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.backends import BM25Backend, ProductionBackend, document_text
from evaluation.dataset import load_dataset


class ProductionParityTests(unittest.TestCase):
    def test_real_chroma_index_can_be_removed_after_search(self):
        import numpy as np
        from chromadb.utils import embedding_functions

        class FixedEmbeddings:
            def encode(self, documents, **kwargs):
                return np.asarray([[1., .5, .25] for _ in documents])

        docs, _ = load_dataset()
        cache = embedding_functions.SentenceTransformerEmbeddingFunction.models
        with patch.dict(cache, {'BAAI/bge-large-en-v1.5': FixedEmbeddings()}):
            with tempfile.TemporaryDirectory(prefix='apirag-cleanup-test-') as directory:
                backend = ProductionBackend(docs, directory)
                self.assertTrue(backend.dense('SandboxPay payment'))
                self.assertTrue(backend.hybrid('SandboxPay payment'))
                backend.close()
            self.assertFalse(Path(directory).exists())

    def test_document_and_bm25_match_production(self):
        from models import APIEntry
        from retrieval.vector_store import VectorStore, _entry_to_document

        docs, _ = load_dataset()
        for doc in docs:
            self.assertEqual(document_text(doc['entry']), _entry_to_document(APIEntry(**doc['entry'])))
        local = BM25Backend(docs)
        production = VectorStore.__new__(VectorStore)
        production._bm25 = local.index
        production._bm25_ids = local.ids
        for query in ['SandboxPay payment', 'zxqnomatch', '', '/v1/events']:
            self.assertEqual([(r['id'], r['score']) for r in local.search(query)],
                             production._bm25_search(query, top_k=20))

    def test_production_reranker_truncation_and_order(self):
        from retrieval.reranker import Reranker

        class Predict:
            def predict(self, pairs):
                self.pairs = pairs
                return [-2, 2]

        reranker = Reranker()
        model = Predict()
        reranker._model = model
        result = reranker.rerank('query', [{'id': 'a', 'document': 'x' * 1000}, {'id': 'b', 'document': 'y'}], top_k=2)
        self.assertEqual([r['id'] for r in result], ['b', 'a'])
        self.assertEqual(len(model.pairs[0][1]), 512)


if __name__ == '__main__':
    unittest.main()
