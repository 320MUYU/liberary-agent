import unittest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from app.common.exceptions import BusinessException
from app.schemas.ai import ChatMessage, ChatRequest
from app.services import ai_services


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


class AIServiceTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
