import unittest

from scripts.evaluate_rag import calculate_retrieval_metrics


class RetrievalMetricsTest(unittest.TestCase):
    def test_recall_counts_all_labels_and_mrr_uses_first_hit(self):
        records = [
            {"expected_ids": ["a", "b"], "ranked_ids": ["x", "a", "a", "b"], "latency_ms": 10},
            {"expected_ids": ["c"], "ranked_ids": ["x", "y"], "latency_ms": 20},
            {"expected_ids": [], "ranked_ids": ["x"], "latency_ms": 30},
            {"expected_ids": [], "ranked_ids": [], "latency_ms": 40},
        ]
        result = calculate_retrieval_metrics(records, k=2)
        self.assertEqual(result["recall_at_k"], 0.25)
        self.assertEqual(result["hit_at_k"], 0.5)
        self.assertEqual(result["mrr_at_k"], 0.25)
        self.assertEqual(result["no_answer_false_positive_rate"], 0.5)
        self.assertEqual(result["latency_p95_ms"], 40)
        self.assertEqual(calculate_retrieval_metrics(records, k=3)["recall_at_k"], 0.5)

    def test_errors_are_misses_not_successful_refusals(self):
        result = calculate_retrieval_metrics([
            {"expected_ids": [1], "ranked_ids": [], "error": "503", "latency_ms": 1},
            {"expected_ids": [], "ranked_ids": [], "error": "503", "latency_ms": 1},
        ])
        self.assertEqual(result["errors"], 2)
        self.assertEqual(result["recall_at_k"], 0)
        self.assertIsNone(result["no_answer_false_positive_rate"])

    def test_empty_input_and_invalid_cutoff(self):
        self.assertIsNone(calculate_retrieval_metrics([])["recall_at_k"])
        for k in (0, -1, True, 1.5):
            with self.subTest(k=k), self.assertRaises(ValueError):
                calculate_retrieval_metrics([], k=k)
