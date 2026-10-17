import unittest
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from app.agent.coordinator import plan_workflow
from app.agent.policy import RunBudget
from app.common.exceptions import BusinessException


class WorkflowCoordinatorTest(unittest.TestCase):
    def model(self, response):
        model = MagicMock()
        model.model_copy.return_value = model
        def bind(*args, **kwargs):
            if "tool_choice" in kwargs:
                raise ValueError("Thinking mode does not support this tool_choice")
            return MagicMock(invoke=lambda _: response)
        model.bind_tools.side_effect = bind
        return model

    def test_thinking_models_use_auto_tool_selection_and_strict_plan_validation(self):
        response = AIMessage(content="", tool_calls=[{"id": "p", "name": "plan_workflow", "args": {
            "steps": [{"task_type": "borrow", "title": "查找", "query": "Python", "read_only": True}]}}])
        with patch("app.agent.coordinator._create_chat_model", return_value=self.model(response)):
            budget = RunBudget()
            self.assertEqual(plan_workflow("查找Python书", budget).steps[0].task_type, "borrow")
            self.assertEqual(budget.models, 1)

    def test_missing_or_forged_plan_tool_never_becomes_a_default_business_task(self):
        for response in (AIMessage(content="已办理"), AIMessage(content="", tool_calls=[{
                "id": "p", "name": "plan_workflow", "args": {"steps": [{"task_type": "admin", "query": "审批", "title": "审批"}]}}])):
            with patch("app.agent.coordinator._create_chat_model", return_value=self.model(response)):
                with self.assertRaises(BusinessException):
                    plan_workflow("未支持的请求", RunBudget())
