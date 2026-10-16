import unittest
from unittest.mock import patch

from scripts.evaluate_retrieval import evaluate, main, validate_dataset


class RetrievalEvaluationTest(unittest.TestCase):
    def test_dataset_requires_explicit_boolean_origin_label(self):
        for data in ([], {}, {"synthetic": "false"}, {"synthetic": 0}):
            with self.assertRaises(ValueError):
                validate_dataset(data, allow_synthetic=True)

    def test_remote_plain_http_is_rejected_before_reading_dataset(self):
        with patch.dict("os.environ", {"RAG_EVAL_TOKEN": "test-token"}), \
                patch("scripts.evaluate_retrieval.Path.read_text") as read, patch("sys.stderr"):
            result = main(["--live", "--dataset", "unused.json", "--api-base-url", "http://example.com"])
        self.assertEqual(result, 2)
        read.assert_not_called()

    def test_synthetic_data_requires_explicit_opt_in_and_valid_labels(self):
        data = {"synthetic": True, "cases": [{"id": "q1", "question": "何时开放", "expected_document_ids": [1]}]}
        with self.assertRaises(ValueError):
            validate_dataset(data)
        validate_dataset(data, allow_synthetic=True)
        for labels in ([True], [0], ["1"]):
            data["cases"][0]["expected_document_ids"] = labels
            with self.assertRaises(ValueError):
                validate_dataset(data, allow_synthetic=True)

    def test_three_strategies_report_candidate_and_final_quality_separately(self):
        data = {"synthetic": False, "cases": [{"id": "q1", "question": "何时开放", "expected_document_ids": [1, 2]}]}
        def search(payload):
            return {"code": 200, "data": {"candidates": [{"document_id": 1}, {"document_id": 2}],
                "results": [{"document_id": 1}], "rerank_status": "fallback" if payload["strategy"] == "hybrid_rerank" else "disabled"}}
        report = evaluate(data, search)
        self.assertEqual(report["strategies"]["vector"]["candidate_metrics"]["recall_at_k"], 1)
        self.assertEqual(report["strategies"]["vector"]["final_metrics"]["recall_at_k"], 0.5)
        self.assertEqual(report["strategies"]["hybrid_rerank"]["rerank_fallbacks"], 1)

    def test_upstream_errors_are_safe_and_not_reported_as_no_match(self):
        data = {"cases": [{"id": "q1", "question": "何时开放", "expected_document_ids": [1]}]}
        report = evaluate(data, lambda payload: {"code": 503, "message": "private-key"})
        self.assertEqual(report["strategies"]["vector"]["final_metrics"]["errors"], 1)
        self.assertNotIn("private-key", str(report))
