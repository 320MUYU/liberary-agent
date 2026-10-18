import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import httpx

from app.services.library_corpus import CorpusManifest
from scripts.evaluate_library import (
    apply_reviews, extract_conversation_answer, make_record, report_identity,
    answer_case, run_live, summarize, validate_bindings, validate_splits, validate_suite,
)


class LibraryEvaluationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.text = "公开规则测试快照：本科生可借20册。"
        (self.root / "rules.md").write_text(self.text, encoding="utf-8")
        self.digest = hashlib.sha256(self.text.encode()).hexdigest()
        self.manifest = CorpusManifest.model_validate({
            "corpus_key": "hust-library", "institution": "华中科技大学图书馆", "scope": "external_reference",
            "sources": [{"key": "rules", "title": "测试规则", "url": "https://lib.hust.edu.cn/#/rules",
                "snapshot": "rules.md", "sha256": self.digest, "observed_at": "2026-10-18T08:00:00+08:00", "category": "borrowing"}],
        })
        self.suite = {"schema_version": 1, "synthetic": False, "corpus_key": "hust-library",
            "split": "calibration", "annotation_author": "agent_assisted", "annotation_review": "pending_human",
            "source_hashes": {"rules": self.digest}, "cases": [{
                "id": "c01", "category": "direct", "fact_group": "undergrad_limit",
                "question": "华科本科生能借几册？", "answerable": True,
                "expected_source_keys": ["rules"], "expected_facts": ["本科生20册"],
                "evidence": [{"source_key": "rules", "quote": "本科生可借20册"}],
            }]}
        self.bindings = {"applied": True, "corpus_key": "hust-library", "scope": "external_reference", "records": [
            {"key": "rules", "snapshot_sha256": self.digest, "document_id": 10,
             "version_id": 20, "version_number": 1, "version_status": "ready",
             "active_version_id": 20, "document_status": "published"}]}
        self.answer = {"retrieval_status": "matched", "content": "华科本科生可借20册。[1]", "sources": [
            {"number": 1, "document_id": 10, "version": 1, "chunk_id": 30, "title": "华科规则", "excerpt": self.text}]}
        self.previews = [{"chunk_id": 30, "document_id": 10, "version": 1, "text": self.text}]

    def test_official_source_suite_requires_exact_snapshot_and_evidence(self):
        validate_suite(self.suite, self.manifest, self.root)
        for change in ("hash", "quote", "synthetic", "source"):
            suite = copy.deepcopy(self.suite)
            if change == "hash": suite["source_hashes"]["rules"] = "0" * 64
            if change == "quote": suite["cases"][0]["evidence"][0]["quote"] = "原文中不存在的事实"
            if change == "synthetic": suite["synthetic"] = "false"
            if change == "source": suite["cases"][0]["expected_source_keys"] = ["unknown"]
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_suite(suite, self.manifest, self.root)

    def test_snapshot_tampering_and_missing_positive_labels_are_rejected(self):
        suite = copy.deepcopy(self.suite)
        suite["cases"][0]["expected_source_keys"] = []
        with self.assertRaises(ValueError):validate_suite(suite, self.manifest, self.root)
        (self.root / "rules.md").write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):validate_suite(self.suite, self.manifest, self.root)

    def test_abstention_case_cannot_claim_unsupported_gold_facts(self):
        suite = copy.deepcopy(self.suite)
        case = suite["cases"][0]
        case["answerable"] = False
        case["abstention_reason"] = "不在本次语料范围"
        with self.assertRaises(ValueError):validate_suite(suite, self.manifest, self.root)
        case.update(expected_source_keys=[], expected_facts=[], evidence=[])
        validate_suite(suite, self.manifest, self.root)

    def test_calibration_and_validation_must_not_share_questions_ids_or_fact_groups(self):
        other = copy.deepcopy(self.suite)
        other["split"] = "validation"
        with self.assertRaises(ValueError):validate_splits(self.suite, other)
        other["cases"][0].update(id="v01", question="另一道问题", fact_group="other")
        validate_splits(self.suite, other)
        for field in ("id", "question", "fact_group"):
            changed = copy.deepcopy(other)
            changed["cases"][0][field] = self.suite["cases"][0][field]
            with self.subTest(field=field), self.assertRaises(ValueError):validate_splits(self.suite, changed)

    def test_bindings_reject_unpublished_replaced_or_different_snapshots(self):
        self.assertEqual(validate_bindings(self.suite, self.bindings)["rules"]["document_id"], 10)
        for field, value in (("active_version_id", 21), ("version_status", "queued"), ("snapshot_sha256", "0" * 64), ("document_id", True)):
            changed = copy.deepcopy(self.bindings)
            changed["records"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):validate_bindings(self.suite, changed)

    def record(self, answer=None, previews=None, **kwargs):
        return make_record(self.suite["cases"][0], answer or self.answer,
            validate_bindings(self.suite, self.bindings), self.previews if previews is None else previews, 10, **kwargs)

    def test_automated_success_does_not_invent_human_accuracy(self):
        record = self.record()
        self.assertTrue(record["contract_pass"])
        metrics = summarize([record])
        self.assertEqual(metrics["contract_pass_rate"], 1)
        self.assertEqual(metrics["human_reviewed"], 0)
        self.assertIsNone(metrics["answer_accuracy"])
        self.assertIsNone(metrics["citation_support_rate"])

    def test_expected_document_returned_but_not_cited_is_a_miss(self):
        answer = copy.deepcopy(self.answer)
        answer["content"] = "一条无关资料。[2]"
        answer["sources"].append({"number": 2, "document_id": 99, "version": 1, "chunk_id": 31})
        record = self.record(answer)
        self.assertFalse(record["contract_pass"])
        self.assertEqual(record["expected_source_coverage"], 0)

    def test_stale_preview_or_wrong_version_cannot_pass(self):
        self.assertFalse(self.record(previews=[])["contract_pass"])
        answer = copy.deepcopy(self.answer)
        answer["sources"][0]["version"] = 2
        self.assertFalse(self.record(answer)["contract_pass"])

    def test_quote_in_an_uncited_chunk_does_not_count_as_supported(self):
        answer = copy.deepcopy(self.answer)
        answer["sources"].append({"number": 2, "document_id": 10, "version": 1, "chunk_id": 31})
        previews = [{**self.previews[0], "text": "无关内容"}, {**self.previews[0], "chunk_id": 31}]
        self.assertFalse(self.record(answer, previews)["contract_pass"])

    def test_service_error_never_counts_as_correct_abstention(self):
        case = {**self.suite["cases"][0], "answerable": False, "expected_source_keys": [], "expected_facts": [], "evidence": []}
        answer = {"retrieval_status": "no_match", "sources": [], "content": "暂无依据"}
        record = make_record(case, answer, {}, [], 10, error="request_failed")
        self.assertFalse(record["contract_pass"])
        self.assertFalse(record["abstained"])
        self.assertEqual(summarize([record])["abstention_rate"], 0)

    def test_both_document_and_fact_quote_coverage_are_reported(self):
        record = self.record()
        self.assertEqual(record["expected_source_coverage"], 1)
        self.assertEqual(record["evidence_quote_coverage"], 1)
        self.assertEqual(record["answer"]["content"], self.answer["content"])
        self.assertEqual(record["previews"][0]["text"], self.text)

    def test_conversation_extraction_uses_only_the_requested_turn_and_task(self):
        view = {"turns": [{"request_id": "old", "workflow_id": "old-task", "reply": None},
                          {"request_id": "new", "workflow_id": "new-task", "reply": None}],
                "tasks": [{"workflow_id": "old-task", "steps": [{"result": {"content": "old"}}]},
                          {"workflow_id": "new-task", "status": "completed", "steps": [
                              {"spec": {"task_type": "knowledge"}, "result": self.answer}]}]}
        answer, trace = extract_conversation_answer(view, "new")
        self.assertEqual(answer["content"], self.answer["content"])
        self.assertEqual(trace["task_types"], ["knowledge"])

    def test_equivalent_official_sources_can_satisfy_one_required_evidence_group(self):
        case = copy.deepcopy(self.suite["cases"][0])
        case["expected_source_keys"] = ["rules", "alternative"]
        case["expected_source_groups"] = [["rules", "alternative"]]
        case["evidence"].append({"source_key": "alternative", "quote": "本科生可借20册"})
        bound = validate_bindings(self.suite, self.bindings)
        bound["alternative"] = {**bound["rules"], "document_id": 11}
        record = make_record(case, self.answer, bound, self.previews, 10)
        self.assertTrue(record["contract_pass"])

    def test_task_answer_takes_precedence_over_conversation_acknowledgment(self):
        view = {"turns": [{"request_id": "new", "workflow_id": "task",
            "reply": {"content": "已按你的需求安排处理步骤，结果与后续操作见下方。"}}],
            "tasks": [{"workflow_id": "task", "status": "completed", "steps": [
                {"spec": {"task_type": "knowledge"}, "result": self.answer}]}]}
        answer, trace = extract_conversation_answer(view, "new")
        self.assertEqual(answer, self.answer)
        self.assertEqual(trace["task_types"], ["knowledge"])

    def test_direct_clarification_without_task_remains_a_direct_reply(self):
        reply = {"content": "请明确要查询哪个图书馆的规定。"}
        answer, trace = extract_conversation_answer({"turns": [
            {"request_id": "new", "workflow_id": None, "reply": reply}], "tasks": []}, "new")
        self.assertEqual(answer, reply)
        self.assertEqual(trace["task_types"], [])

    def test_conversation_runner_advances_only_current_ready_task_without_confirmation(self):
        seen = []
        request_id = None
        def handler(req):
            nonlocal request_id
            seen.append(req.url.path)
            if req.url.path == "/api/conversations":data = {}
            elif req.url.path.endswith("/messages"):
                payload = json.loads(req.content)
                request_id = payload["request_id"]
                self.assertEqual(payload["hint"], "auto")
                data = {"turns": [{"request_id": request_id, "workflow_id": "current"}], "tasks": [
                    {"workflow_id": "old", "status": "ready"}, {"workflow_id": "current", "status": "ready"}]}
            elif req.url.path.endswith("/tasks/current/retry"):
                data = {"turns": [{"request_id": request_id, "workflow_id": "current"}], "tasks": [
                    {"workflow_id": "current", "status": "completed", "steps": [
                        {"spec": {"task_type": "knowledge"}, "result": self.answer}]}]}
            else:self.fail("unexpected operation")
            return httpx.Response(200, json={"code": 200, "data": data})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            answer, trace = answer_case(client, "http://localhost", self.suite["cases"][0], "conversation")
        self.assertEqual(answer["content"], self.answer["content"])
        self.assertEqual(len(seen), 3)

    def test_three_consecutive_service_failures_stop_and_never_pass_the_gate(self):
        suite = copy.deepcopy(self.suite)
        suite["cases"] = [{**suite["cases"][0], "id": f"c{index}"} for index in range(5)]
        def handler(req):
            if req.method == "GET":
                data = [{"id": 10, "status": "published", "active_version_id": 20,
                    "versions": [{"id": 20, "status": "ready", "version_number": 1}]}]
                return httpx.Response(200, json={"code": 200, "data": data})
            return httpx.Response(503, json={"code": 503, "message": "private provider text"})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            report = run_live(suite, self.bindings, client, "http://localhost", entrypoint="knowledge")
        self.assertFalse(report["automatic_gate_pass"])
        self.assertEqual(report["metrics"]["errors"], 3)
        self.assertEqual(len(report["results"]), 3)
        self.assertNotIn("private provider text", json.dumps(report))

    def test_reviews_are_bound_to_exact_run_and_missing_reviews_remain_pending(self):
        report = {"results": [self.record()], "dataset_sha256": "1" * 64}
        report["report_id"] = report_identity(report)
        reviews = {"report_id": report["report_id"], "cases": [{"id": "c01", "reviewer": "人工审核人",
            "answer_correct": True, "citations_support": True, "notes": "逐项核对原文"}]}
        apply_reviews(report, reviews)
        self.assertEqual(summarize(report["results"])["answer_accuracy"], 1)
        reviews["report_id"] = "wrong"
        with self.assertRaises(ValueError):apply_reviews(report, reviews)
        reviews["report_id"] = report["report_id"]
        reviews["cases"][0]["answer_correct"] = None
        with self.assertRaises(ValueError):apply_reviews(report, reviews)


