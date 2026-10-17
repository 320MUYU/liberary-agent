import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agent.policy import RunBudget, WorkflowBudget, BudgetExceeded
from app.agent.specialists import invoke_specialist
from app.common.exceptions import BusinessException


class WorkflowSpecialistsTest(unittest.TestCase):
    def test_parent_reservation_happens_before_every_model_or_tool_call(self):
        charged = []
        budget = WorkflowBudget(reserve=charged.append, max_models=1)
        budget.consume("model"); budget.consume("tool")
        self.assertEqual(charged, ["model", "tool"])
        with self.assertRaises(BudgetExceeded):
            budget.consume("model")
        self.assertEqual(charged, ["model", "tool"])

    def test_read_only_specialist_cannot_prepare_or_confirm_a_write(self):
        step = SimpleNamespace(child_run_id="child", spec={"task_type": "borrow", "read_only": True, "query": "找书", "title": "找书"})
        for operation in ("select", "select_loan", "select_space", "decision"):
            with self.assertRaises(BusinessException):
                invoke_specialist(None, 1, step, None, RunBudget(), operation, {})

    def test_specialists_keep_separate_child_ids_and_task_context(self):
        db = SimpleNamespace(query=lambda *_: SimpleNamespace(filter_by=lambda **_: SimpleNamespace(first=lambda: None)))
        budget = RunBudget()
        with patch("app.agent.specialists.runtime.start_run", return_value={}) as start:
            for kind, child in (("borrow", "book-child"), ("reservation", "space-child")):
                step = SimpleNamespace(child_run_id=child, spec={"task_type": kind, "read_only": False, "query": kind, "title": kind})
                invoke_specialist(db, 1, step, None, budget)
                self.assertEqual(start.call_args.args[2:5], (child, kind, kind))
                self.assertIs(start.call_args.kwargs["budget"], budget)
