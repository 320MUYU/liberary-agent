"""Review workbench behavior, independent of model/network calls."""

import copy
import unittest

from types import SimpleNamespace
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.models.users import User
from app.models.evaluation_review import EvaluationRun, EvaluationCaseReview
from app.schemas.evaluation_review import ReviewDecision
from app.services import evaluation_review_service as service
from scripts.upgrade_evaluation_reviews import upgrade

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

    def test_import_rejects_missing_statistics_fields_and_unaddressable_case_ids(self):
        for field in ("error", "expected_source_coverage"):
            report = sample_report()
            del report["results"][0][field]
            report["report_id"] = report_identity(report)
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_report(report)
        for case_id in ("a/b", "..", " c0", "c1:KNOWLEDGE"):
            report = sample_report()
            report["results"][0]["id"] = case_id
            report["report_id"] = report_identity(report)
            with self.subTest(case_id=case_id), self.assertRaises(ValueError):
                validate_report(report)

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


class ReviewStorageTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        User.__table__.create(self.engine)
        upgrade(self.engine, apply=True)
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.db.add(User(id=7, username="review-admin", password="hash", name="审核员", role="admin"))
        self.db.commit()
        self.admin = SimpleNamespace(id=7, username="review-admin", name="审核员")
        self.run = service.import_report(self.db, sample_report(), "测试报告", self.admin)

    def decision(self, **kwargs):
        return ReviewDecision.model_validate({"revision": 0, "status": "draft", **kwargs})

    def test_migration_preview_repeatability_and_old_data(self):
        self.assertEqual(upgrade(self.engine, apply=True), [])
        self.assertEqual(self.db.scalar(text("SELECT username FROM users")), "review-admin")
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        self.assertEqual(len(upgrade(engine)), 2)
        self.assertFalse(inspect(engine).has_table(EvaluationRun.__tablename__))

    def test_reimport_preserves_draft_and_imported_reviews_are_untrusted(self):
        saved = service.save_review(self.db, self.run["id"], "c0:knowledge", self.decision(
            answer_correct=False, notes="待核对"), self.admin)
        report = sample_report()
        report["results"][0]["review"] = {"status": "reviewed", "answer_correct": True}
        again = service.import_report(self.db, report, "另一个名字", self.admin)
        self.assertEqual(again["id"], self.run["id"])
        self.assertEqual(service.get_case(self.db, self.run["id"], "c0:knowledge")["review"], saved["review"])
        self.assertEqual(len(self.db.scalars(select(EvaluationCaseReview)).all()), 2)
        self.assertEqual(again["metrics"]["human_reviewed"], 0)

    def test_submit_identity_timestamp_filter_metrics_and_cli_export(self):
        saved = service.save_review(self.db, self.run["id"], "c0:knowledge", self.decision(
            status="reviewed", answer_correct=False, citations_support=True, notes="遗漏"), self.admin)
        review = saved["review"]
        self.assertEqual(review["reviewer_id"], 7)
        self.assertIn("review-admin", review["reviewer"])
        self.assertIsNotNone(review["reviewed_at"])
        self.assertEqual(review["revision"], 1)
        detail = service.get_run(self.db, self.run["id"], "human_negative")
        self.assertEqual(len(detail["cases"]), 1)
        self.assertEqual(detail["metrics"]["human_review_coverage"], .5)
        self.assertEqual(detail["metrics"]["answer_accuracy"], 0)
        self.assertEqual(len(service.get_run(self.db, self.run["id"], "pending")["cases"]), 1)
        self.assertEqual(len(service.get_run(self.db, self.run["id"], "automatic_failure")["cases"]), 0)
        exported = service.export_reviews(self.db, self.run["id"])
        merged = apply_reviews(sample_report(), exported)
        self.assertEqual(merged["metrics"], service.export_report(self.db, self.run["id"])["metrics"])
        self.assertEqual(len(exported["cases"]), 1)
        self.assertEqual(service.list_runs(self.db)[0]["metrics"]["human_reviewed"], 1)

    def test_stale_revision_cannot_overwrite_and_error_case_cannot_pass(self):
        run_id = self.run["id"]
        service.save_review(self.db, run_id, "c0:knowledge", self.decision(notes="first"), self.admin)
        with self.assertRaises(BusinessException) as error:
            service.save_review(self.db, run_id, "c0:knowledge", self.decision(notes="stale"), self.admin)
        self.assertEqual(error.exception.code, 409)
        self.assertEqual(service.get_case(self.db, run_id, "c0:knowledge")["review"]["notes"], "first")
        report = sample_report()
        report["results"][0]["error"] = "failed"
        report["report_id"] = report_identity(report)
        other = service.import_report(self.db, report, "失败报告", self.admin)
        with self.assertRaises(BusinessException):
            service.save_review(self.db, other["id"], "c0:knowledge", self.decision(
                status="reviewed", answer_correct=True, citations_support=True), self.admin)
        with self.assertRaises(BusinessException):
            service.get_case(self.db, run_id, "unknown")

    def test_editing_submitted_review_as_draft_excludes_it_until_resubmission(self):
        run_id = self.run["id"]
        service.save_review(self.db, run_id, "c0:knowledge", self.decision(
            status="reviewed", answer_correct=True, citations_support=True), self.admin)
        service.save_review(self.db, run_id, "c0:knowledge", self.decision(revision=1, notes="重审"), self.admin)
        self.assertEqual(service.export_reviews(self.db, run_id)["cases"], [])
        self.assertIsNone(service.get_run(self.db, run_id)["metrics"]["answer_accuracy"])
