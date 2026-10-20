import math
import unittest

from evaluation.metrics import aggregate, paired_delta, retrieval_metrics


class MetricTests(unittest.TestCase):
    def test_known_ranking_and_multi_source_recall(self):
        result = retrieval_metrics(['noise', 'a', 'b'], {'a': 2, 'b': 1})
        self.assertEqual(result['recall@1'], 0)
        self.assertEqual(result['recall@5'], 1)
        self.assertEqual(result['mrr@10'], .5)
        expected = (3 / math.log2(3) + 1 / math.log2(4)) / (3 + 1 / math.log2(3))
        self.assertAlmostEqual(result['ndcg@10'], expected)

    def test_empty_prediction_is_zero_and_no_labels_is_not_perfect(self):
        self.assertEqual(retrieval_metrics([], {'a': 1})['mrr@10'], 0)
        self.assertIsNone(retrieval_metrics(['a'], {}))
        self.assertIsNone(retrieval_metrics([], {}))

    def test_duplicate_results_rejected(self):
        with self.assertRaises(ValueError):
            retrieval_metrics(['a', 'a'], {'a': 1})

    def test_cutoff_and_partial_recall(self):
        result = retrieval_metrics(['a'] + [str(i) for i in range(10)] + ['b'], {'a': 1, 'b': 1})
        self.assertEqual(result['recall@1'], .5)
        self.assertEqual(result['recall@5'], .5)
        self.assertEqual(result['mrr@10'], 1)

    def test_bootstrap_is_seeded_and_empty_is_missing(self):
        self.assertIsNone(aggregate([]))
        rows = [retrieval_metrics(['a'], {'a': 1})] * 3
        self.assertEqual(aggregate(rows), aggregate(rows))
        self.assertEqual(aggregate(rows)['mrr@10']['ci95'], [1, 1])
        self.assertEqual(paired_delta(rows, rows)['mrr@10']['mean'], 0)


if __name__ == '__main__':
    unittest.main()
