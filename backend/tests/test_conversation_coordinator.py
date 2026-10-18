import unittest
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.agent.coordinator import route_conversation
from app.common.exceptions import BusinessException
from app.schemas.conversation import ConversationDecision


class ConversationCoordinatorTest(unittest.TestCase):
    def test_route_uses_history_task_results_and_hint_with_auto_tool_selection(self):
        decision = {"action": "plan", "plan": {"steps": [
            {"task_type": "borrow", "title": "再查第二本", "query": "Python 第二版", "read_only": True}]}}
        model = MagicMock()
        model.model_copy.return_value = model
        model.bind_tools.return_value.invoke.return_value = AIMessage(content="", tool_calls=[
            {"id": "route", "name": "route_conversation", "args": decision}])
        with patch("app.agent.coordinator._create_chat_model", return_value=model):
            result = route_conversation("第二本有库存吗", [{"role": "user", "content": "找Python书"}],
                [{"workflow_id": "task", "books": [{"title": "Python 第二版"}]}], "library")
        self.assertEqual(result.plan.steps[0].query, "Python 第二版")
        self.assertNotIn("tool_choice", model.bind_tools.call_args.kwargs)
        prompt = str(model.bind_tools.return_value.invoke.call_args.args)
        for expected in ("第二本有库存吗", "Python 第二版", "library", "Asia/Shanghai"):
            self.assertIn(expected, prompt)

    def test_read_only_text_steps_and_decisions_cannot_carry_confirmation(self):
        for kind in ("chat", "knowledge", "space_query"):
            route = ConversationDecision(action="plan", plan={"steps": [
                {"task_type": kind, "title": "回答", "query": "规则", "read_only": False}]})
            self.assertTrue(route.plan.steps[0].read_only)
        for invalid in ({"action": "confirm", "confirmed": True},
                {"action": "conditions"}, {"action": "plan"},
                {"action": "ask", "message": "请说明", "workflow_id": "not-an-id"}):
            with self.assertRaises(ValidationError):
                ConversationDecision.model_validate(invalid)

    def test_unstructured_model_output_is_not_treated_as_a_business_result(self):
        model = MagicMock()
        model.model_copy.return_value = model
        model.bind_tools.return_value.invoke.return_value = AIMessage(content="已预约成功")
        with patch("app.agent.coordinator._create_chat_model", return_value=model):
            with self.assertRaises(BusinessException):
                route_conversation("预约", [], [], "auto")
