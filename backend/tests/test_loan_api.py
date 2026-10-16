import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from app.api.loan import router
from app.common.exceptions import (
    BusinessException,
    business_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.schemas.loan import LoanResponse


def create_test_client(role=None):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(BusinessException, business_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.dependency_overrides[get_db] = lambda: "test-session"
    if role:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=7, role=role, status=1
        )
    return TestClient(app)


def loan_response():
    return LoanResponse(
        id=1, book_id=2, book_title="Python 入门", reader_id=7,
        reader_name="读者", reader_username="reader", status="pending",
        create_time=datetime(2026, 10, 16, 10, 0), is_overdue=False,
    )


class LoanApiTest(unittest.TestCase):
    def test_reader_operations_require_login(self):
        client = create_test_client()
        operations = (
            ("GET", "/loans", {}),
            ("POST", "/loans", {"json": {"book_id": 2}}),
            ("POST", "/loans/1/cancel", {}),
            ("POST", "/loans/1/request-return", {}),
        )
        for method, path, arguments in operations:
            with self.subTest(path=path):
                self.assertEqual(client.request(method, "/api" + path, **arguments).status_code, 401)

    def test_admin_operations_require_admin_for_all_routes(self):
        operations = (
            ("GET", "/admin/loans", {}),
            ("POST", "/admin/loans/1/confirm-borrow", {"json": {}}),
            ("POST", "/admin/loans/1/reject", {"json": {"reason": "盘点中"}}),
            ("POST", "/admin/loans/1/confirm-return", {}),
        )
        for role, expected in ((None, 401), ("student", 403)):
            client = create_test_client(role)
            for method, path, arguments in operations:
                with self.subTest(role=role, path=path):
                    self.assertEqual(client.request(method, "/api" + path, **arguments).status_code, expected)

    @patch("app.api.loan.loan_service.loan_response")
    @patch("app.api.loan.loan_service.create_loan")
    def test_apply_uses_authenticated_identity_and_unified_response(self, create, serialize):
        create.return_value = "loan"
        serialize.return_value = loan_response()
        response = create_test_client("student").post("/api/loans", json={"book_id": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 200)
        self.assertEqual(response.json()["data"]["reader_id"], 7)
        self.assertEqual(create.call_args.args[0], "test-session")
        self.assertEqual(create.call_args.args[1].id, 7)
        self.assertEqual(create.call_args.args[2].book_id, 2)

    @patch("app.api.loan.loan_service.list_my_loans")
    def test_reader_page_filters_and_pagination(self, listing):
        listing.return_value = (1, [loan_response()])
        response = create_test_client("student").get("/api/loans?page=2&page_size=10&status=pending")
        self.assertEqual(response.json()["data"]["page"], 2)
        self.assertEqual(response.json()["data"]["total"], 1)
        args = listing.call_args.args
        self.assertEqual(args[0], "test-session")
        self.assertEqual(args[1].id, 7)
        self.assertEqual(args[2:], (2, 10, "pending"))

    @patch("app.api.loan.loan_service.list_loans_page")
    def test_admin_page_forwards_status_keyword(self, listing):
        listing.return_value = (1, [loan_response()])
        response = create_test_client("admin").get("/api/admin/loans?status=pending&keyword=reader")
        self.assertEqual(response.json()["data"]["items"][0]["book_title"], "Python 入门")
        listing.assert_called_once_with("test-session", 1, 10, "pending", "reader")

    @patch("app.api.loan.loan_service.create_loan")
    def test_invalid_request_rejected_before_service(self, create):
        client = create_test_client("student")
        for value in (0, -1, True, "2"):
            with self.subTest(value=value):
                self.assertEqual(client.post("/api/loans", json={"book_id": value}).status_code, 422)
        create.assert_not_called()

    def test_pagination_path_copy_and_rejection_validation(self):
        reader = create_test_client("student")
        admin = create_test_client("admin")
        for path in ("/api/loans?page=0", "/api/loans?page_size=101", "/api/loans/0/cancel"):
            with self.subTest(path=path):
                method = reader.post if path.endswith("cancel") else reader.get
                self.assertEqual(method(path).status_code, 422)
        self.assertEqual(admin.post("/api/admin/loans/1/confirm-borrow", json={"copy_id": 0}).status_code, 422)
        self.assertEqual(admin.post("/api/admin/loans/1/reject", json={"reason": "   "}).status_code, 422)

    @patch("app.api.loan.loan_service.loan_response")
    @patch("app.api.loan.loan_service.confirm_borrow")
    def test_confirm_passes_copy_and_admin_identity(self, confirm, serialize):
        confirm.return_value = "loan"
        serialize.return_value = loan_response()
        response = create_test_client("admin").post("/api/admin/loans/1/confirm-borrow", json={"copy_id": 3})
        self.assertEqual(response.json()["code"], 200)
        self.assertEqual(confirm.call_args.args[1].id, 7)
        self.assertEqual(confirm.call_args.args[2], 1)
        self.assertEqual(confirm.call_args.args[3].copy_id, 3)

    @patch("app.api.loan.loan_service.cancel_loan")
    def test_business_conflict_preserves_code(self, cancel):
        cancel.side_effect = BusinessException("当前状态不能取消", 409)
        response = create_test_client("student").post("/api/loans/1/cancel")
        self.assertEqual(response.json()["code"], 409)


if __name__ == "__main__":
    unittest.main()
