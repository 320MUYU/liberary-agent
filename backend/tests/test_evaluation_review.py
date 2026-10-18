"""Review workbench behavior, independent of model/network calls."""

import copy
import unittest

from app.services.evaluation_reports import (
    apply_reviews, report_identity, summarize, validate_report,
)


def sample_report(count=2):
    rows = [{
        "id": f"c{i}:knowledge", "question": f"测试题 {i}", "prelude": ["前一个问题"],
        "answerable": True, "expected_facts": ["20册"],
        "expected_evidence": [{"source_key": "rules", "quote": "本科生可借20册"}],
        "answer": {"content": "可借20册。[1]", "retrieval_status": "matched", "sources": [
            {"number": 1, "chunk_id": 1, "title": "规则", "excerpt": "可借20册"}]},
        "previews": [{"chunk_id": 1, "text": "完整原文：本科生可借20册。"}],
        "error": None, "contract_pass": True, "expected_source_coverage": 1,
        "citation_valid": True, "abstained": False, "latency_ms": 10,
        "review": {"status": "pending_human"},
    } for i in range(count)]
    report = {"synthetic": True, "split": "test", "results": rows}
    report["report_id"] = report_identity(report)
    return report


class ReportValidationTest(unittest.TestCase):
    def test_legacy_script_exports_the_shared_functions(self):
        from scripts import evaluate_library
        self.assertIs(evaluate_library.summarize, summarize)
        self.assertIs(evaluate_library.apply_reviews, apply_reviews)
        self.assertIs(evaluate_library.report_identity, report_identity)

    def test_identity_checks_answer_evidence_and_unique_case_ids(self):
        for field in ("answer", "previews", "expected_facts"):
            report = sample_report()
            report["results"][0][field] = {} if field == "answer" else []
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_report(report)
        report = sample_report()
        report["results"][1]["id"] = report["results"][0]["id"]
        report["report_id"] = report_identity(report)
        with self.assertRaises(ValueError):
            validate_report(report)

    def test_import_ignores_external_reviews_and_metrics_without_mutating_input(self):
        report = sample_report()
        report["metrics"] = {"answer_accuracy": 1}
        report["results"][0]["review"] = {"status": "reviewed", "answer_correct": True}
        original = copy.deepcopy(report)
        clean = validate_report(report)
        self.assertEqual(report, original)
        self.assertEqual(clean["metrics"]["human_reviewed"], 0)
        self.assertIsNone(clean["metrics"]["answer_accuracy"])
        self.assertEqual(clean["results"][0]["review"], {"status": "pending_human"})

    def test_malformed_reports_are_rejected_with_value_error(self):
        for value in (None, [], {}, {"results": []}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_report(value)
        for field, value in (("latency_ms", float("nan")), ("answerable", 1),
                             ("answer", []), ("expected_facts", "x"), ("previews", [None])):
            report = sample_report()
            report["results"][0][field] = value
            report["report_id"] = report_identity(report)
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_report(report)

    def test_pending_draft_and_partial_review_metrics_are_separate(self):
        report = sample_report(3)
        report["results"][0]["review"] = {"status": "draft", "answer_correct": True}
        result = apply_reviews(report, {"report_id": report["report_id"], "cases": [{
            "id": "c1:knowledge", "reviewer": "admin", "answer_correct": False,
            "citations_support": True, "notes": "有遗漏",
        }]})
        self.assertEqual(result["metrics"]["human_reviewed"], 1)
        self.assertAlmostEqual(result["metrics"]["human_review_coverage"], 1 / 3)
        self.assertEqual(result["metrics"]["answer_accuracy"], 0)
        self.assertEqual(result["metrics"]["citation_support_rate"], 1)
        self.assertEqual(result["review_status"], "pending_human")

    def test_legacy_review_rejects_duplicates_wrong_report_and_error_as_correct(self):
        report = sample_report()
        item = {"id": "c0:knowledge", "reviewer": "admin", "answer_correct": True,
                "citations_support": True}
        for cases in ([item, item], [{**item, "id": "unknown"}], [{**item, "reviewer": ""}],
                      [{**item, "answer_correct": 1}]):
            with self.assertRaises(ValueError):
                apply_reviews(copy.deepcopy(report), {"report_id": report["report_id"], "cases": cases})
        report["results"][0]["error"] = "failed"
        report["report_id"] = report_identity(report)
        with self.assertRaises(ValueError):
            apply_reviews(report, {"report_id": report["report_id"], "cases": [item]})
