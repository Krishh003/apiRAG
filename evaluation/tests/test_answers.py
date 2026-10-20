import unittest
from unittest.mock import patch

from evaluation.answers import BM25AnswerBackend, CallBudget, TimedModel, review_rows, review_summary, validate_reviews
from evaluation.dataset import load_dataset
from evaluation.performance import validate_local_url


class AnswerReviewTests(unittest.TestCase):
    def test_model_calls_are_paced_and_quota_failure_suppresses_further_requests(self):
        from google.api_core.exceptions import ResourceExhausted

        class Model:
            def __init__(self):
                self.calls = 0

            def generate_content(self, prompt, **kwargs):
                self.calls += 1
                raise ResourceExhausted('test quota')

        model = Model()
        calls = []
        budget = CallBudget(interval_seconds=13)
        wrapped = TimedModel(model, 'gemini-test', calls, {}, budget)
        with self.assertRaises(ResourceExhausted):
            wrapped.generate_content('test')
        with self.assertRaises(RuntimeError):
            wrapped.generate_content('test again')
        self.assertEqual(model.calls, 1)
        self.assertFalse(calls[1]['api_request_sent'])

    def test_throttle_is_per_model_and_outside_api_timer(self):
        budget = CallBudget(interval_seconds=13)
        with patch('evaluation.answers.time.monotonic', side_effect=[100, 105, 106]), patch('evaluation.answers.time.sleep') as sleep:
            self.assertEqual(budget.before_call('flash'), 0)
            self.assertEqual(budget.before_call('flash'), 8000)
            self.assertEqual(budget.before_call('pro'), 0)
            sleep.assert_called_once_with(8)

    def test_bm25_answer_control_returns_real_documents_and_preserves_order(self):
        docs, _ = load_dataset()
        backend = BM25AnswerBackend(docs)
        results = backend.store.hybrid_search('SandboxPay payment', top_k=4)
        self.assertEqual(len(results), 4)
        self.assertTrue(all('document' in row and 'metadata' in row for row in results))
        self.assertEqual(backend.reranker.rerank('query', results, top_k=2), results[:2])
        self.assertEqual(backend.store.count(), 25)

    def test_bm25_answer_control_respects_filters_and_empty_query(self):
        docs, _ = load_dataset()
        backend = BM25AnswerBackend(docs)
        self.assertEqual(backend.store.hybrid_search('', top_k=4), [])
        results = backend.store.hybrid_search('SandboxPay payment', top_k=4, platform_filter='SandboxNotify')
        self.assertTrue(all(row['metadata']['platform'] == 'SandboxNotify' for row in results))

    def test_pending_reviews_are_not_passes(self):
        rows = [dict(query_id='q1', answerable=False, review={})]
        self.assertEqual(review_summary(rows)['reviewed'], 0)
        self.assertIsNone(review_summary(rows)['factual_correctness'])

    def test_review_without_an_actual_answer_is_rejected(self):
        row = dict(query_id='q1', answerable=False, answer=None, review=dict(
            reviewer='human-a', factual_correctness=2, grounding=2,
            unsupported_claims=0, abstained=True, notes='No response exists.'))
        with self.assertRaises(ValueError):
            validate_reviews([row])

    def test_prepare_rejects_unrun_configuration(self):
        docs, questions = load_dataset()
        with self.assertRaises(ValueError):
            review_rows([], docs, questions, config='reranked')

    def test_manual_scoring_and_abstention_denominator(self):
        rows = [dict(query_id='q1', answerable=False, answer='Unknown; invented detail.', review=dict(
            reviewer='human-a', factual_correctness=1, grounding=0,
            unsupported_claims=1, abstained=True, notes='Invented a detail despite saying unknown.')),
            dict(query_id='q2', answerable=True, answer='Supported facts.', review=dict(
                reviewer='human-a', factual_correctness=2, grounding=2,
                unsupported_claims=0, abstained=False, notes='Checked source facts.'))]
        result = review_summary(rows)
        self.assertEqual(result['reviewed'], 2)
        self.assertEqual(result['factual_correctness'], .75)
        self.assertEqual(result['missing_information_abstention'], 1)
        self.assertEqual(result['unsupported_claim_rate'], .5)

    def test_invalid_or_duplicate_reviews_rejected(self):
        with self.assertRaises(ValueError):
            validate_reviews([dict(query_id='q1', review={'factual_correctness': 3})])
        with self.assertRaises(ValueError):
            validate_reviews([dict(query_id='q1', review={})] * 2)

    def test_load_test_rejects_remote_and_malformed_url(self):
        for url in ['https://example.com', 'http://127.0.0.1.evil.example', 'http://user:secret@localhost:8000', 'file:///tmp/x']:
            with self.assertRaises(ValueError):
                validate_local_url(url)
        self.assertEqual(validate_local_url('http://127.0.0.1:8000'), 'http://127.0.0.1:8000')


if __name__ == '__main__':
    unittest.main()
