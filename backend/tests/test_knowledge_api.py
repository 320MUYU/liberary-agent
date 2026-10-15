import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from app.api.knowledge import router
from app.common.exceptions import (
    BusinessException,
    business_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.database import get_db
from app.dependencies.auth import get_current_user


def create_test_client(role=None):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(BusinessException, business_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.dependency_overrides[get_db] = lambda: "test-session"
    if role is not None:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=7, role=role
        )
    return TestClient(app)


def document():
    version = SimpleNamespace(
        id=2,
        document_id=1,
        version_number=1,
        original_name="馆规.txt",
        status="ready",
        chunk_count=3,
        error_message=None,
        storage_name="private/secret-file.txt",
        sha256="a" * 64,
    )
    return SimpleNamespace(
        id=1,
        title="馆规",
        status="published",
        active_version_id=2,
        latest_version_id=2,
        uploaded_by=7,
        versions=[version],
    )


class KnowledgeApiTest(unittest.TestCase):
    def test_all_admin_operations_require_admin_role(self):
        operations = (
            ("GET", "/documents", {}),
            (
                "POST",
                "/documents",
                {"data": {"title": "馆规"}, "files": {"file": ("rules.txt", b"rules")}},
            ),
            (
                "POST",
                "/documents/1/versions",
                {"files": {"file": ("rules.txt", b"rules")}},
            ),
            ("POST", "/documents/1/publish", {}),
            ("POST", "/documents/1/disable", {}),
            ("POST", "/versions/2/retry", {}),
            ("DELETE", "/documents/1", {}),
        )
        for role, expected_status in ((None, 401), ("student", 403)):
            client = create_test_client(role)
            for method, path, kwargs in operations:
                with self.subTest(role=role, method=method, path=path):
                    response = client.request(
                        method, "/api/admin/knowledge" + path, **kwargs
                    )
                    self.assertEqual(response.status_code, expected_status)

    @patch("app.api.knowledge.knowledge_service.list_documents")
    def test_admin_list_has_safe_unified_response(self, list_documents):
        list_documents.return_value = [document()]
        response = create_test_client("admin").get("/api/admin/knowledge/documents")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 200)
        item = response.json()["data"][0]
        self.assertEqual(item["title"], "馆规")
        self.assertNotIn("storage_name", item["versions"][0])
        self.assertNotIn("sha256", item["versions"][0])
        list_documents.assert_called_once_with("test-session")

    @patch("app.api.knowledge.knowledge_service.upload_document", new_callable=AsyncMock)
    def test_upload_uses_admin_identity_and_trims_title(self, upload_document):
        upload_document.return_value = document()
        response = create_test_client("admin").post(
            "/api/admin/knowledge/documents",
            data={"title": "  馆规  "},
            files={"file": ("rules.txt", "馆规".encode(), "text/plain")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["id"], 1)
        args, kwargs = upload_document.call_args
        self.assertEqual(args[0], "test-session")
        self.assertEqual(kwargs["title"], "馆规")
        self.assertEqual(kwargs["user_id"], 7)
        self.assertIsNone(kwargs.get("document_id"))

    @patch("app.api.knowledge.knowledge_service.upload_document", new_callable=AsyncMock)
    def test_upload_new_version_selects_existing_document(self, upload_document):
        upload_document.return_value = document()
        response = create_test_client("admin").post(
            "/api/admin/knowledge/documents/1/versions",
            files={"file": ("rules.txt", b"rules", "text/plain")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(upload_document.call_args.kwargs["document_id"], 1)
        self.assertEqual(upload_document.call_args.kwargs["title"], "")

    @patch("app.api.knowledge.knowledge_service.upload_document", new_callable=AsyncMock)
    def test_upload_rejects_blank_title_without_calling_service(self, upload_document):
        response = create_test_client("admin").post(
            "/api/admin/knowledge/documents",
            data={"title": "   "},
            files={"file": ("rules.txt", b"rules", "text/plain")},
        )
        self.assertEqual(response.status_code, 422)
        upload_document.assert_not_called()

    @patch("app.api.knowledge.knowledge_service.publish_document")
    def test_publish_forwards_version_and_rejects_invalid_version(self, publish):
        publish.return_value = document()
        client = create_test_client("admin")
        response = client.post("/api/admin/knowledge/documents/1/publish?version_id=2")
        self.assertEqual(response.json()["data"]["status"], "published")
        publish.assert_called_once_with("test-session", 1, 2)

        invalid = client.post("/api/admin/knowledge/documents/1/publish?version_id=0")
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(publish.call_count, 1)

    @patch("app.api.knowledge.knowledge_service.disable_document")
    @patch("app.api.knowledge.knowledge_service.retry_version")
    @patch("app.api.knowledge.knowledge_service.delete_document")
    def test_disable_retry_and_delete_use_unified_responses(self, delete, retry, disable):
        disabled = document()
        disabled.status = "disabled"
        disable.return_value = disabled
        retry.return_value = disabled.versions[0]
        client = create_test_client("admin")

        disabled_response = client.post("/api/admin/knowledge/documents/1/disable")
        retried = client.post("/api/admin/knowledge/versions/2/retry")
        deleted = client.delete("/api/admin/knowledge/documents/1")

        self.assertEqual(disabled_response.json()["data"]["status"], "disabled")
        self.assertEqual(retried.json()["data"]["id"], 2)
        self.assertNotIn("storage_name", retried.json()["data"])
        self.assertEqual(deleted.json()["code"], 200)
        self.assertIsNone(deleted.json()["data"])
        disable.assert_called_once_with("test-session", 1)
        retry.assert_called_once_with("test-session", 2)
        delete.assert_called_once_with("test-session", 1)

    def test_source_preview_requires_login(self):
        response = create_test_client().get("/api/knowledge/sources/1")
        self.assertEqual(response.status_code, 401)

    @patch("app.api.knowledge.knowledge_service.get_source")
    def test_source_preview_accepts_readers_and_filters_internal_fields(self, get_source):
        get_source.return_value = {
            "chunk_id": 1,
            "document_id": 1,
            "version": 2,
            "title": "馆规",
            "page": 3,
            "section": "借阅须知",
            "text": "保持安静。",
            "storage_name": "private/secret-file.txt",
            "embedding_profile": "internal",
        }
        response = create_test_client("student").get("/api/knowledge/sources/1")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["text"], "保持安静。")
        self.assertNotIn("storage_name", data)
        self.assertNotIn("embedding_profile", data)
        get_source.assert_called_once_with("test-session", 1)

    @patch("app.api.knowledge.knowledge_service.get_source")
    def test_unpublished_or_disabled_source_errors_remain_business_errors(self, get_source):
        get_source.side_effect = BusinessException("来源文档已停用或不存在", code=404)
        response = create_test_client("student").get("/api/knowledge/sources/1")
        self.assertEqual(response.json()["code"], 404)
        self.assertIsNone(response.json()["data"])

    @patch("app.api.knowledge.knowledge_service.get_source")
    def test_invalid_source_ids_never_call_service(self, get_source):
        client = create_test_client("student")
        for chunk_id in ("0", "-1", "chunk-1"):
            with self.subTest(chunk_id=chunk_id):
                response = client.get(f"/api/knowledge/sources/{chunk_id}")
                self.assertEqual(response.status_code, 422)
        get_source.assert_not_called()

    def test_main_api_registers_management_and_authenticated_source_routes(self):
        from app.main import app

        paths = {route.path for route in app.routes}
        self.assertIn("/api/admin/knowledge/documents", paths)
        self.assertIn("/api/knowledge/sources/{chunk_id}", paths)


if __name__ == "__main__":
    unittest.main()
