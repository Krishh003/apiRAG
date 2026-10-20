import unittest

from evaluation.answers import review_rows, review_summary, validate_reviews
from evaluation.dataset import load_dataset
from evaluation.performance import validate_local_url


class AnswerReviewTests(unittest.TestCase):
    def test_pending_reviews_are_not_passes(self):
        rows = [dict(query_id='q1', answerable=False, review={})]
        self.assertEqual(review_summary(rows)['reviewed'], 0)
        self.assertIsNone(review_summary(rows)['factual_correctness'])

    def test_prepare_rejects_unrun_configuration(self):
        docs, questions = load_dataset()
        with self.assertRaises(ValueError):
            review_rows([], docs, questions, config='reranked')

    def test_manual_scoring_and_abstention_denominator(self):
        rows = [dict(query_id='q1', answerable=False, review=dict(
            reviewer='human-a', factual_correctness=1, grounding=0,
            unsupported_claims=1, abstained=True, notes='Invented a detail despite saying unknown.')),
            dict(query_id='q2', answerable=True, review=dict(
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
