import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.evaluate_rag import calculate_metrics, load_dataset, main, run_offline


DATASET = Path(__file__).parent / "fixtures" / "rag_evaluation.json"


class RagEvaluationTest(unittest.TestCase):
    def test_fixture_is_explicitly_synthetic_and_covers_required_scenarios(self):
        dataset = load_dataset(DATASET)
        self.assertTrue(dataset["synthetic"])
        self.assertGreaterEqual(len(dataset["cases"]), 30)
        categories = {case["category"] for case in dataset["cases"]}
        self.assertTrue({"hit", "no_match", "disabled", "follow_up", "injection"}.issubset(categories))
        self.assertTrue(all("合成" in document["title"] for document in dataset["documents"]))

    def test_offline_evaluation_never_constructs_network_adapters(self):
        with (
            patch("app.services.rag_service.create_embeddings", side_effect=AssertionError("network forbidden")),
            patch("app.services.rag_service.ChromaVectorStore", side_effect=AssertionError("network forbidden")),
            patch("app.services.ai_services.get_knowledge_model", side_effect=AssertionError("network forbidden")),
        ):
            report = run_offline(load_dataset(DATASET))

        self.assertEqual(report["mode"], "offline")
        self.assertTrue(report["synthetic"])
        self.assertIn("不代表", report["scope"])
        self.assertEqual(report["metrics"]["total"], 30)
        self.assertEqual(report["metrics"]["passed"], 30)
        self.assertEqual(report["metrics"]["retrieval_hit_rate"], 1.0)
        self.assertEqual(report["metrics"]["citation_validity_rate"], 1.0)
        self.assertEqual(report["metrics"]["no_match_refusal_rate"], 1.0)
        self.assertGreaterEqual(report["metrics"]["latency_p95_ms"], 0)

    def test_metrics_count_failed_retrieval_citations_and_refusals(self):
        base = {
            "expected_status": "matched", "actual_status": "matched",
            "expected_document_ids": [1], "actual_document_ids": [1],
            "citation_valid": True, "latency_ms": 10, "error": None,
        }
        records = [
            dict(base),
            {**base, "actual_document_ids": [2], "citation_valid": False, "latency_ms": 20},
            {**base, "expected_status": "no_match", "expected_document_ids": [],
             "actual_status": "no_match", "actual_document_ids": [], "latency_ms": 30},
            {**base, "expected_status": "no_match", "expected_document_ids": [],
             "actual_status": "error", "actual_document_ids": [], "error": "503", "latency_ms": 40},
        ]

        metrics = calculate_metrics(records)

        self.assertEqual(metrics["retrieval_hits"], 1)
        self.assertEqual(metrics["retrieval_misses"], 1)
        self.assertEqual(metrics["retrieval_hit_rate"], 0.5)
        self.assertEqual(metrics["citation_validity_rate"], 0.5)
        self.assertEqual(metrics["no_match_refusal_rate"], 0.5)
        self.assertEqual(metrics["errors"], 1)
        self.assertEqual(metrics["latency_p95_ms"], 40)

    def test_live_mode_refuses_synthetic_dataset_before_network(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertEqual(main(["--live", "--dataset", str(DATASET)]), 2)
        self.assertIn("合成", output.getvalue())

    def test_default_cli_outputs_machine_readable_offline_report(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main([])
        self.assertEqual(result, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["mode"], "offline")
        self.assertEqual(report["metrics"]["total"], 30)


if __name__ == "__main__":
    unittest.main()
