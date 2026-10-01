import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from app.api.ai import router
from app.common.exceptions import http_exception_handler, validation_exception_handler
from app.dependencies.auth import get_current_user
from app.schemas.ai import ChatResponse


def create_test_app(authenticated: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    return app


class AIApiTest(unittest.TestCase):
    def test_chat_requires_login(self):
        client = TestClient(create_test_app(authenticated=False))

        response = client.post(
            "/api/ai/chat",
            json={"messages": [{"role": "user", "content": "你好"}]},
        )

        self.assertEqual(response.status_code, 401)

    @patch("app.api.ai.ai_services.chat")
    def test_chat_returns_unified_response(self, mock_chat):
        mock_chat.return_value = ChatResponse(content="你好，我能帮你了解预约流程。")
        client = TestClient(create_test_app(authenticated=True))

        response = client.post(
            "/api/ai/chat",
            json={"messages": [{"role": "user", "content": "你好"}]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "code": 200,
                "message": "请求成功",
                "data": {
                    "role": "assistant",
                    "content": "你好，我能帮你了解预约流程。",
                },
            },
        )
        mock_chat.assert_called_once()

    def test_main_api_registers_chat_route(self):
        from app.main import app

        route_paths = {route.path for route in app.routes}
        self.assertIn("/api/ai/chat", route_paths)


if __name__ == "__main__":
    unittest.main()
