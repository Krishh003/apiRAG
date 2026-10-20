import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.backends import BM25Backend, production_rrf
from evaluation.dataset import load_dataset, read_jsonl
from evaluation.run import evaluate, score_predictions


class HarnessTests(unittest.TestCase):
    def test_rrf_preserves_existing_missing_rank_rule(self):
        scores = production_rrf(['a', 'b'], ['b', 'c'])
        self.assertAlmostEqual(scores['a'], 1 / 61 + 1 / 64)
        self.assertAlmostEqual(scores['b'], 1 / 62 + 1 / 61)

    def test_rrf_empty(self):
        self.assertEqual(production_rrf([], []), {})

    def test_bm25_empty_and_oov(self):
        backend = BM25Backend([])
        self.assertEqual(backend.search('query'), [])
        docs, _ = load_dataset()
        backend = BM25Backend(docs)
        self.assertEqual(backend.search(''), [])
        self.assertEqual(backend.search('zxqnomatch'), [])

    def test_real_bm25_run_recomputed_from_predictions(self):
        docs, questions = load_dataset()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            summary = evaluate(docs, questions, path, bm25_only=True, repeats=1, concurrent_requests=4)
            rows = read_jsonl(path / 'predictions.jsonl')
            recomputed = score_predictions(rows, questions)
            self.assertEqual(summary['retrieval'], recomputed['retrieval'])
            self.assertEqual(len(rows), 100)
            self.assertEqual(summary['retrieval']['bm25']['overall']['mrr@10']['n'], 87)
            self.assertEqual(summary['stages']['dense']['status'], 'incomplete')
            self.assertEqual(summary['concurrency']['n'], 4)

    def test_scoring_rejects_missing_or_unknown_predictions(self):
        _, questions = load_dataset()
        with self.assertRaises(ValueError):
            score_predictions([dict(query_id='unknown', config='bm25', repeat=0, predicted_ids=[])], questions)
        with self.assertRaises(ValueError):
            score_predictions([dict(query_id=questions[0]['id'], config='bm25', repeat=0, predicted_ids=[])], questions)

    def test_first_inference_failure_preserves_bm25_and_error_evidence(self):
        class BrokenBackend:
            def __init__(self, docs, path):
                pass

            def load_reranker(self):
                pass

            def dense(self, question):
                raise RuntimeError('first inference failed')

        docs, questions = load_dataset()
        with tempfile.TemporaryDirectory() as directory, patch('evaluation.run.ProductionBackend', BrokenBackend):
            result = evaluate(docs, questions, Path(directory), concurrent_requests=1)
            self.assertEqual(result['stages']['dense']['status'], 'incomplete')
            self.assertIn('bm25', result['retrieval'])
            self.assertTrue(read_jsonl(Path(directory) / 'errors.jsonl'))

    def test_request_failures_mark_stage_failed_and_count_latency_attempts(self):
        class BrokenAfterWarmup:
            def __init__(self, docs, path):
                self.calls = 0

            def load_reranker(self):
                raise RuntimeError('missing weights')

            def model_manifest(self):
                return {}

            def dense(self, question):
                self.calls += 1
                if self.calls > 1:
                    raise RuntimeError('inference failure')
                return []

            def hybrid(self, question):
                return []

        docs, questions = load_dataset()
        with tempfile.TemporaryDirectory() as directory, patch('evaluation.run.ProductionBackend', BrokenAfterWarmup):
            result = evaluate(docs, questions, Path(directory), concurrent_requests=1)
            self.assertEqual(result['stages']['dense']['status'], 'failed')
            self.assertEqual(result['stages']['dense']['failed'], 100)
            self.assertEqual(result['latencies']['dense']['n'], 100)
            self.assertEqual(result['retrieval']['dense']['overall']['mrr@10']['mean'], 0)


if __name__ == '__main__':
    unittest.main()
