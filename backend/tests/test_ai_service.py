import json
from datetime import datetime
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from app.common.exceptions import BusinessException
from app.schemas.ai import ChatMessage, ChatRequest
from app.services import ai_services
from app.services.time_context import BEIJING


class FakeChatModel:
    def __init__(self, response: AIMessage | None = None, error: Exception | None = None):
        self.response = response or AIMessage(content="测试回答")
        self.error = error
        self.received_messages = None

    def invoke(self, messages):
        self.received_messages = messages
        if self.error:
            raise self.error
        return self.response

    def bind_tools(self, definitions):
        self.definitions = definitions
        return self

    def model_copy(self, update):
        return self


class AIServiceTest(unittest.TestCase):
    def test_structured_answer_survives_generation_and_requests_readable_format(self):
        content = "**结论：**可以提交申请。\n\n1. 选择空间。\n2. 核对时间，提交后等待审核。"
        model = FakeChatModel(AIMessage(content=content))
        result = ai_services.chat(self.request(), model=model)
        self.assertEqual(result.content, content)
        self.assertIn("结论在前", model.received_messages[0].content)
        self.assertIn("Markdown", model.received_messages[0].content)
        self.assertIn("不能替用户提交或修改预约", model.received_messages[0].content)

    def request(self):
        return ChatRequest(
            messages=[
                ChatMessage(role="assistant", content="你好"),
                ChatMessage(role="user", content="如何预约学习空间？"),
            ]
        )

    def test_chat_builds_langchain_messages_and_returns_answer(self):
        model = FakeChatModel(AIMessage(content=" 请在学习空间列表中提交预约。 "))

        result = ai_services.chat(self.request(), model=model)

        self.assertEqual(result.role, "assistant")
        self.assertEqual(result.content, "请在学习空间列表中提交预约。")
        self.assertIsInstance(model.received_messages[0], SystemMessage)
        self.assertIsInstance(model.received_messages[1], AIMessage)
        self.assertIsInstance(model.received_messages[2], HumanMessage)
        self.assertIn("不要编造", model.received_messages[0].content)
        self.assertIn("尚未接入 RAG", model.received_messages[0].content)

    def test_request_rejects_blank_content_and_non_user_last_message(self):
        with self.assertRaises(ValidationError):
            ChatMessage(role="user", content="   ")

        with self.assertRaises(ValidationError):
            ChatRequest(messages=[ChatMessage(role="assistant", content="回答")])

    def test_model_error_is_mapped_to_business_exception(self):
        model = FakeChatModel(error=RuntimeError("network error"))

        with self.assertRaises(BusinessException) as raised:
            ai_services.chat(self.request(), model=model)

        self.assertEqual(raised.exception.code, 503)
        self.assertEqual(raised.exception.message, "AI 服务暂时不可用，请稍后重试")

    def test_empty_model_response_is_rejected(self):
        model = FakeChatModel(AIMessage(content="   "))

        with self.assertRaises(BusinessException) as raised:
            ai_services.chat(self.request(), model=model)

        self.assertEqual(raised.exception.code, 502)

    def test_missing_api_key_has_clear_error(self):
        original_api_key = ai_services.settings.DEEPSEEK_API_KEY
        ai_services.settings.DEEPSEEK_API_KEY = None
        ai_services.get_chat_model.cache_clear()
        try:
            with self.assertRaises(BusinessException) as raised:
                ai_services.chat(self.request())
        finally:
            ai_services.settings.DEEPSEEK_API_KEY = original_api_key
            ai_services.get_chat_model.cache_clear()

        self.assertEqual(raised.exception.code, 503)
        self.assertEqual(raised.exception.message, "AI 服务尚未配置，请联系管理员")

    def test_every_chat_injects_trusted_current_beijing_time(self):
        model = FakeChatModel()
        with patch("app.services.ai_services.now_beijing", return_value=datetime(2026, 10, 18, 0, 30, tzinfo=BEIJING)):
            ai_services.chat(self.request(), model=model)
        system = model.received_messages[0].content
        self.assertIn("2026-10-18", system)
        self.assertIn("周日", system)
        self.assertIn("Asia/Shanghai", system)

    def test_multi_turn_slot_query_passes_only_server_identity_and_live_tool_evidence(self):
        class SequenceModel(FakeChatModel):
            def invoke(self, messages):
                self.received_messages = list(messages)
                if any(message.type == "tool" for message in messages):
                    evidence = json.loads(messages[-1].content)
                    return AIMessage(content="10月24日14:00—16:00，" + evidence["data"]["spaces"][0]["name"])
                return AIMessage(content="", tool_calls=[{"id": "slot", "name": "check_space_availability",
                    "args": {"date_expression": "2026-10-24", "start": "14:00", "end": "16:00"}}])
        model = SequenceModel()
        request = ChatRequest(messages=[
            ChatMessage(role="user", content="周六有自习室吗"),
            ChatMessage(role="assistant", content="指2026年10月24日吗？需要哪个时段？"),
            ChatMessage(role="user", content="对，14点到16点"),
        ])
        db = object()
        with patch("app.services.ai_services.execute_chat_tool", return_value={"ok": True,
                "data": {"spaces": [{"name": "数据库中的自习室"}]}}) as read:
            result = ai_services.chat(request, model=model, db=db, user_id=7)
        self.assertIn("数据库中的自习室", result.content)
        self.assertEqual(read.call_args.args[:2], (db, 7))
        self.assertEqual(model.received_messages[-1].tool_call_id, "slot")

    def test_tool_failures_stop_generation_and_never_return_model_claimed_success(self):
        model = FakeChatModel(AIMessage(content="已经预约成功", tool_calls=[{
            "id": "x", "name": "search_space_catalogue", "args": {}}]))
        with patch("app.services.ai_services.execute_chat_tool", return_value={
                "ok": False, "error_code": "unavailable", "message": "空间查询暂时不可用"}):
            result = ai_services.chat(self.request(), model=model, user_id=1)
        self.assertIn("暂时不可用", result.content)
        self.assertNotIn("成功", result.content)

    def test_repeated_tool_calls_hit_a_finite_budget(self):
        model = FakeChatModel(AIMessage(content="", tool_calls=[{
            "id": "clock", "name": "resolve_date_expression", "args": {"expression": "明天"}}]))
        with patch("app.services.ai_services.execute_chat_tool", return_value={
                "ok": True, "data": {"date": "2026-10-19"}}) as read:
            result = ai_services.chat(self.request(), model=model, user_id=1)
        self.assertLessEqual(read.call_count, 8)
        self.assertIn("上限", result.content)

    def test_date_clarification_keeps_already_supplied_time(self):
        model = FakeChatModel(AIMessage(content="", tool_calls=[{
            "id": "date", "name": "check_space_availability",
            "args": {"date_expression": "周六", "start": "14:00", "end": "16:00"}}]))
        with patch("app.services.ai_services.execute_chat_tool", return_value={"ok": True, "data": {
                "status": "needs_clarification", "message": "请确认日期。",
                "candidates": [{"date": "2026-10-24", "weekday": "周六"}]}}):
            result = ai_services.chat(self.request(), model=model)
        self.assertIn("已收到14:00—16:00", result.content)
        self.assertNotIn("需明确起止时间", result.content)


if __name__ == "__main__":
    unittest.main()
