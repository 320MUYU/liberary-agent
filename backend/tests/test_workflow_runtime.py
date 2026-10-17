import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import unittest

from langchain_core.messages import AIMessage
from sqlalchemy import func, select

from app.agent import workflow
from app.common.exceptions import BusinessException
from app.models.agent import AgentRun
from app.models.loans import Loan
from app.models.labs import Lab
from app.models.reservations import Reservation
from app.models.workflow import WorkflowRun, WorkflowStep
from app.schemas.workflow import WorkflowPlan
from tests import test_loan_service as fixtures


class WorkflowRuntimeTest(unittest.TestCase):
    setUp = fixtures.LoanServiceTest.setUp
    add_book = fixtures.LoanServiceTest.add_book

    def setup_workflow(self, tasks=None, conditions=None):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        for name, value in (("AGENT_CHECKPOINT_PATH", Path(folder.name) / "checkpoint.sqlite"), ("AGENT_TOOL_TRANSPORT", "local")):
            config = patch("app.agent.runtime.settings." + name, value); config.start(); self.addCleanup(config.stop)
        self.tasks = tasks or [{"task_type": "borrow", "query": "Python", "title": "找书", "read_only": False}]
        def plan(query, budget):
            budget.consume("model")
            return WorkflowPlan(steps=self.tasks)
        planner = patch("app.agent.workflow.plan_workflow", side_effect=plan)
        planner.start(); self.addCleanup(planner.stop)
        def model(messages, budget, task_type="borrow"):
            budget.consume("model")
            if any(getattr(m, "type", "") == "tool" for m in messages):
                return AIMessage(content="")
            tool, args = ("search_spaces", {}) if task_type == "reservation" else (
                ("list_my_loans", {}) if task_type in {"return", "my_loans"} else
                ("search_books", {"keyword": "Python", "mode": "exact"}))
            return AIMessage(content="", tool_calls=[{"id": "find", "name": tool, "args": args}])
        fake = patch("app.agent.runtime.call_model", side_effect=model)
        fake.start(); self.addCleanup(fake.stop)
        return workflow.create_workflow(self.db, self.reader.id, str(uuid4()), "找 Python 图书", conditions)

    def operate(self, run, op="retry", payload=None):
        return workflow.operate(self.db, self.reader.id, run["workflow_id"], op, payload)

    def test_plan_does_not_start_child_until_advanced_and_replay_is_bound(self):
        run = self.setup_workflow()
        self.assertEqual(run["status"], "ready")
        self.assertEqual(self.db.scalar(select(func.count()).select_from(AgentRun)), 0)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Loan)), 0)
        same = workflow.create_workflow(self.db, self.reader.id, run["workflow_id"], "找 Python 图书")
        self.assertEqual(same["steps"], run["steps"])
        with self.assertRaises(BusinessException):
            workflow.create_workflow(self.db, self.reader.id, run["workflow_id"], "改成其他问题")
        with self.assertRaises(BusinessException):
            workflow.operate(self.db, self.other.id, run["workflow_id"])

    def test_two_steps_keep_first_receipt_and_retry_only_failed_second(self):
        task = {"task_type": "borrow", "query": "Python", "title": "借书", "read_only": False}
        run = self.setup_workflow([task, {**task, "title": "另一步"}])
        run = self.operate(run)
        step_id = run["steps"][0]["id"]
        selected = self.operate(run, "select", {"step_id": step_id, "book_id": self.book.id})
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Loan)), 0)
        action_id = selected["steps"][0]["result"]["action"]["id"]
        payload = {"step_id": step_id, "action_id": action_id, "confirmed": True}
        run = self.operate(run, "decision", payload)
        self.assertEqual(run["steps"][0]["status"], "completed")
        replay = self.operate(run, "decision", payload)
        self.assertEqual(replay["steps"][0]["result"]["receipt"], run["steps"][0]["result"]["receipt"])
        with patch("app.agent.workflow.invoke_specialist", side_effect=BusinessException("临时故障", 503)):
            failed = self.operate(run)
        self.assertEqual(failed["status"], "partial_failure")
        restored = self.operate(failed)
        self.assertEqual(restored["steps"][1]["result"]["status"], "select_book")
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Loan)), 1)

    def test_lost_committed_response_recovers_original_child_and_does_not_replan(self):
        run = self.setup_workflow()
        original = workflow.invoke_specialist
        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise BusinessException("响应丢失", 503)
        with patch("app.agent.workflow.invoke_specialist", side_effect=lost):
            run = self.operate(run)
        child = run["steps"][0]["child_run_id"]
        run = self.operate(run)
        self.assertEqual(run["steps"][0]["child_run_id"], child)
        self.assertEqual(run["steps"][0]["result"]["status"], "select_book")
        self.assertEqual(self.db.scalar(select(func.count()).select_from(AgentRun)), 1)

    def test_conditions_must_be_explicit_and_immutable(self):
        run = self.setup_workflow([{"task_type": "reservation", "query": "研讨室", "title": "预约", "read_only": False}])
        self.assertEqual(run["status"], "needs_conditions")
        self.operate(run)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(AgentRun)), 0)
        conditions = {"date": str(date.today() + timedelta(days=2)), "start": "14:00", "end": "16:00", "people": 3, "purpose": "讨论"}
        run = self.operate(run, "conditions", {"conditions": conditions})
        self.assertEqual(run["status"], "ready")
        with self.assertRaises(BusinessException):
            self.operate(run, "conditions", {"conditions": {**conditions, "people": 4}})

    def test_read_only_query_finishes_without_writes_and_cannot_confirm(self):
        run = self.setup_workflow([{**{"task_type": "borrow", "query": "Python", "title": "查找"}, "read_only": True}])
        run = self.operate(run)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["steps"][0]["result"]["status"], "select_book")
        with self.assertRaises(BusinessException):
            self.operate(run, "select", {"step_id": run["steps"][0]["id"], "book_id": self.book.id})
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Loan)), 0)

    def test_global_budget_is_durable_across_retries_and_child_legacy_route_is_blocked(self):
        run = self.setup_workflow()
        parent = self.db.query(WorkflowRun).filter_by(workflow_id=run["workflow_id"]).one()
        parent.model_calls = workflow.MAX_MODELS; self.db.commit()
        run = self.operate(run)
        self.assertEqual(run["status"], "budget_exceeded")
        self.assertEqual(self.operate(run)["budget"]["model_calls"], workflow.MAX_MODELS)
        from app.agent.runtime import run_graph
        with self.assertRaises(BusinessException):
            run_graph(self.db, self.reader.id, run["steps"][0]["child_run_id"], "retry")

    def test_cancel_keeps_submitted_business_and_never_starts_next_step(self):
        task = {"task_type": "borrow", "query": "Python", "title": "找书", "read_only": True}
        run = self.setup_workflow([task, task])
        run = self.operate(run)
        run = self.operate(run, "cancel")
        self.assertEqual(run["status"], "cancelled")
        self.assertEqual(self.operate(run)["status"], "cancelled")
        self.assertEqual(self.db.scalar(select(func.count()).select_from(AgentRun)), 1)

    def test_lease_and_expiry_prevent_concurrent_or_stale_advance(self):
        run = self.setup_workflow()
        parent = self.db.query(WorkflowRun).filter_by(workflow_id=run["workflow_id"]).one()
        from datetime import datetime
        parent.lease_until = datetime.now() + timedelta(minutes=2); self.db.commit()
        with self.assertRaises(BusinessException):
            self.operate(run)
        parent.lease_until = None; parent.expires_at = datetime.now() - timedelta(seconds=1); self.db.commit()
        with self.assertRaises(BusinessException):
            self.operate(run)

    def test_confirm_commit_then_lost_response_replays_one_business_receipt(self):
        run = self.operate(self.setup_workflow())
        step_id = run["steps"][0]["id"]
        run = self.operate(run, "select", {"step_id": step_id, "book_id": self.book.id})
        from app.agent.actions import decide_borrow
        def lost(*args):
            decide_borrow(*args)
            raise RuntimeError("lost response after commit")
        with patch("app.agent.runtime.decide_borrow", side_effect=lost):
            with self.assertRaises(BusinessException):
                self.operate(run, "decision", {"step_id": step_id,
                    "action_id": run["steps"][0]["result"]["action"]["id"], "confirmed": True})
        run = self.operate(run)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Loan)), 1)
        before = run["budget"].copy()
        self.assertEqual(before["model_calls"], self.operate(run, "view")["budget"]["model_calls"])

    def test_clarification_waits_and_reserved_child_cannot_be_started_externally(self):
        run = self.setup_workflow()
        from app.agent.runtime import start_run
        with self.assertRaises(BusinessException):
            start_run(self.db, self.reader.id, run["steps"][0]["child_run_id"], "其他查询")
        with patch("app.agent.workflow.plan_workflow", return_value=WorkflowPlan(steps=[], clarification="需要图书还是空间？")):
            run = workflow.create_workflow(self.db, self.reader.id, str(uuid4()), "帮我安排")
        self.assertEqual(run["status"], "needs_clarification")
        self.assertEqual(self.operate(run)["status"], "needs_clarification")
        run = self.operate(run, "clarify", {"text": "查询Python图书"})
        self.assertEqual(run["status"], "planning")
        self.assertEqual(self.operate(run)["status"], "ready")

    def test_fixed_cross_business_cases_use_real_services_and_independent_checkpoints(self):
        import json
        cases = json.loads((Path(__file__).parent / "fixtures/workflows.json").read_text(encoding="utf-8"))["cases"]
        room = Lab(name="工作流合成空间", code="WF-ROOM", building="测试馆", floor="1", capacity=6, category="研讨室")
        self.db.add(room); self.db.commit()
        room_id = room.id
        conditions = {"date": str(date.today() + timedelta(days=3)), "start": "14:00", "end": "16:00", "people": 3, "purpose": "合成测试"}
        for case in cases:
            with self.subTest(case=case["name"]):
                if "return" in case["types"]:
                    from app.services import loan_service
                    from app.schemas.loan import BorrowConfirmRequest
                    pending = self.db.query(Loan).filter_by(reader_id=self.reader.id, status="pending").first()
                    loan_service.confirm_borrow(self.db, self.admin, pending.id, BorrowConfirmRequest())
                tasks = [{"task_type": kind, "query": "Python" if kind == "borrow" else "查询", "title": kind,
                    "read_only": not case["writes"]} for kind in case["types"]]
                run = self.setup_workflow(tasks, conditions)
                ids = [step["child_run_id"] for step in run["steps"]]
                self.assertEqual(len(set(ids)), len(ids))
                for index, kind in enumerate(case["types"]):
                    run = self.operate(run)
                    if not case["writes"]:
                        continue
                    result = run["steps"][index]["result"]
                    step_id = run["steps"][index]["id"]
                    operation, selection = ("select_space", {"space_id": room_id}) if kind == "reservation" else (
                        ("select_loan", {"loan_id": next(l["id"] for l in result["loans"] if l["status"] == "borrowed")})
                        if kind == "return" else ("select", {"book_id": self.book.id}))
                    run = self.operate(run, operation, {"step_id": step_id, **selection})
                    action = run["steps"][index]["result"]["action"]
                    run = self.operate(run, "decision", {"step_id": step_id, "action_id": action["id"], "confirmed": True})
                self.assertEqual(run["status"], "completed")
                self.assertEqual(self.operate(run, "view")["status"], "completed")
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Loan)), 1)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Reservation)), 1)

    def test_failed_external_call_is_charged_before_rollback_and_parent_lease_releases(self):
        run = self.setup_workflow()
        def failed(db, user_id, step, conditions, budget):
            budget.consume("model"); budget.consume("tool")
            raise BusinessException("工具故障", 503)
        with patch("app.agent.workflow.invoke_specialist", side_effect=failed):
            failed_run = self.operate(run)
        self.assertEqual(failed_run["budget"]["model_calls"], run["budget"]["model_calls"] + 1)
        self.assertEqual(failed_run["budget"]["tool_calls"], 1)
        self.assertEqual(self.operate(run)["steps"][0]["result"]["status"], "select_book")

    def test_refresh_never_reactivates_a_skipped_selection(self):
        run = self.operate(self.setup_workflow())
        step_id = run["steps"][0]["id"]
        run = self.operate(run, "skip", {"step_id": step_id})
        self.assertEqual(run["steps"][0]["status"], "skipped")
        restored = self.operate(run, "view")
        self.assertEqual(restored["steps"][0]["status"], "skipped")
        self.assertEqual(restored["status"], "completed")
