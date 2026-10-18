import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agent.specialists import invoke_specialist
from app.agent import workflow
from app.agent.policy import RunBudget, BudgetExceeded
from app.schemas.ai import ChatResponse
from tests import test_workflow_runtime as fixtures


class ConversationSpecialistsTest(unittest.TestCase):
    def test_shared_budget_exhaustion_is_not_a_successful_answer(self):
        from app.services import ai_services, rag_service
        from app.schemas.ai import ChatRequest
        data = ChatRequest(messages=[{"role": "user", "content": "你好"}])
        budget = RunBudget(max_models=0)
        with patch("app.services.ai_services.get_chat_model", return_value=object()):
            with self.assertRaises(BudgetExceeded):
                ai_services.chat(data, budget=budget, unified=True)
        with self.assertRaises(BudgetExceeded):
            rag_service._invoke(object(), [], 9999999999, RunBudget(max_models=0))

    def test_text_specialist_preserves_sources_and_view_never_generates(self):
        step = SimpleNamespace(child_run_id="child", result=None, spec={"task_type": "knowledge",
            "query": "预约规则？", "title": "规则", "read_only": True})
        db = SimpleNamespace(query=lambda *_: SimpleNamespace(filter_by=lambda **_: SimpleNamespace(first=lambda: None)))
        answer = ChatResponse(content="需审核 [1]", sources=[{"number": 1, "chunk_id": 1,
            "document_id": 1, "title": "规则", "version": 1, "excerpt": "需审核"}], retrieval_status="matched")
        with patch("app.agent.specialists.ai_services.chat", return_value=answer) as chat:
            self.assertIsNone(invoke_specialist(db, 1, step, None, RunBudget(), "view"))
            result = invoke_specialist(db, 1, step, None, RunBudget())
            self.assertEqual(result["sources"][0]["chunk_id"], 1)
            self.assertEqual(chat.call_args.args[0].mode, "knowledge")
            step.result = result
            self.assertEqual(invoke_specialist(db, 1, step, None, RunBudget(), "view"), result)
            self.assertEqual(chat.call_count, 1)


class ConversationWorkflowTest(unittest.TestCase):
    setUp = fixtures.WorkflowRuntimeTest.setUp
    add_book = fixtures.WorkflowRuntimeTest.add_book
    setup_workflow = fixtures.WorkflowRuntimeTest.setup_workflow
    operate = fixtures.WorkflowRuntimeTest.operate

    def test_knowledge_then_book_keeps_evidence_in_the_next_step_context(self):
        tasks = [{"task_type": "knowledge", "query": "借书规则", "title": "规则", "read_only": True},
            {"task_type": "chat", "query": "解释上一步", "title": "解释", "read_only": True}]
        run = self.setup_workflow(tasks)
        with patch("app.agent.specialists.ai_services.chat", return_value=ChatResponse(content="已发布规则 [1]")) as chat:
            run = self.operate(run)
            self.assertEqual(run["steps"][0]["status"], "completed")
            run = self.operate(run)
            self.assertIn("已发布规则", str(chat.call_args.args[0].messages))
            self.assertEqual(run["status"], "completed")
            self.operate(run, "view")
            self.assertEqual(chat.call_count, 2)

    def test_earlier_knowledge_can_run_before_missing_reservation_conditions(self):
        run = self.setup_workflow([
            {"task_type": "knowledge", "query": "预约规则", "title": "规则", "read_only": True},
            {"task_type": "reservation", "query": "预约研讨室", "title": "预约", "read_only": False}])
        self.assertEqual(run["status"], "ready")
        with patch("app.agent.specialists.ai_services.chat", return_value=ChatResponse(content="规则 [1]")):
            run = self.operate(run)
        self.assertEqual(run["steps"][0]["status"], "completed")
        run = self.operate(run)
        self.assertEqual(run["status"], "needs_conditions")
        self.assertIsNone(run["steps"][1]["result"])
