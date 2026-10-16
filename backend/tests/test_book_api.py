import unittest
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.book import router
from app.common.exceptions import (
    BusinessException,
    business_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.database import Base, get_db
from app.dependencies.auth import get_current_user


class BookApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api")
        self.app.add_exception_handler(HTTPException, http_exception_handler)
        self.app.add_exception_handler(BusinessException, business_exception_handler)
        self.app.add_exception_handler(RequestValidationError, validation_exception_handler)
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def login(self, role):
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role=role)

    def create_book(self, **changes):
        values = {"title": "Python 入门", "author": "作者", "category": "计算机"}
        values.update(changes)
        response = self.client.post("/api/admin/books", json=values)
        self.assertEqual(response.json()["code"], 200)
        return response.json()["data"]

    def test_every_admin_route_checks_login_and_admin_role(self):
        operations = (
            ("GET", "/admin/books", None),
            ("POST", "/admin/books", {"title": "书", "author": "作者"}),
            ("PUT", "/admin/books/1", {"title": "书", "author": "作者"}),
            ("GET", "/admin/books/1/copies", None),
            ("POST", "/admin/book-copies", {"book_id": 1, "barcode": "A", "location": "A"}),
            ("PUT", "/admin/book-copies/1", {"barcode": "A", "location": "A"}),
        )
        for role, expected in ((None, 401), ("student", 403)):
            if role:
                self.login(role)
            for method, path, body in operations:
                with self.subTest(role=role, path=path, method=method):
                    response = self.client.request(method, "/api" + path, json=body)
                    self.assertEqual(response.status_code, expected)

    def test_public_routes_require_authentication(self):
        for path in ("/api/books", "/api/books/1"):
            self.assertEqual(self.client.get(path).status_code, 401)

    def test_reader_search_and_detail_hide_inactive_books_and_return_inventory(self):
        self.login("admin")
        active = self.create_book()
        inactive = self.create_book(title="未上架", is_active=False)
        self.client.post("/api/admin/book-copies", json={"book_id": active["id"], "barcode": "LIB-001", "location": "A"})
        self.login("student")
        response = self.client.get("/api/books?keyword=Python&category=计算机&page_size=1")
        data = response.json()["data"]
        self.assertEqual((data["total"], data["page"], data["page_size"]), (1, 1, 1))
        self.assertEqual(data["items"][0]["available_copies"], 1)
        detail = self.client.get(f"/api/books/{active['id']}").json()
        self.assertEqual(detail["data"]["total_copies"], 1)
        self.assertEqual(self.client.get(f"/api/books/{inactive['id']}").json()["code"], 404)

    def test_admin_can_filter_inactive_and_update_full_book(self):
        self.login("admin")
        book = self.create_book(description="简介")
        self.create_book(title="未上架", is_active=False)
        self.assertEqual(self.client.get("/api/admin/books").json()["data"]["total"], 2)
        self.assertEqual(self.client.get("/api/admin/books?is_active=false").json()["data"]["total"], 1)
        updated = self.client.put(f"/api/admin/books/{book['id']}", json={"title": "已更新", "author": "作者", "is_active": False})
        self.assertEqual(updated.json()["data"]["title"], "已更新")
        self.assertIsNone(updated.json()["data"]["description"])

    def test_admin_copy_workflow_and_duplicate_errors_use_unified_response(self):
        self.login("admin")
        book = self.create_book(isbn="9787115428028")
        duplicate = self.client.post("/api/admin/books", json={"title": "重复", "author": "作者", "isbn": "9787115428028"})
        self.assertEqual(duplicate.json()["code"], 409)
        payload = {"book_id": book["id"], "barcode": "LIB-001", "location": "A"}
        created = self.client.post("/api/admin/book-copies", json=payload).json()["data"]
        self.assertEqual(self.client.post("/api/admin/book-copies", json=payload).json()["code"], 409)
        updated = self.client.put(f"/api/admin/book-copies/{created['id']}", json={"barcode": "LIB-001", "location": "B", "status": "withdrawn"})
        self.assertEqual(updated.json()["data"]["status"], "withdrawn")
        copies = self.client.get(f"/api/admin/books/{book['id']}/copies?page_size=1").json()["data"]
        self.assertEqual(copies["total"], 1)
        self.assertEqual(copies["items"][0]["location"], "B")

    def test_invalid_parameters_and_uncontrolled_inventory_are_rejected(self):
        self.login("admin")
        requests = (
            ("GET", "/api/books?page=0", None),
            ("GET", "/api/books?page_size=101", None),
            ("GET", "/api/admin/books?is_active=unknown", None),
            ("GET", "/api/admin/books/1/copies?page_size=0", None),
            ("POST", "/api/admin/books", {"title": " ", "author": "作者"}),
            ("POST", "/api/admin/books", {"title": "书", "author": "作者", "available_copies": 100}),
            ("POST", "/api/admin/book-copies", {"book_id": 1, "barcode": "A", "location": "A", "status": "borrowed"}),
            ("PUT", "/api/admin/book-copies/1", {"book_id": 2, "barcode": "A", "location": "A"}),
        )
        for method, path, body in requests:
            with self.subTest(path=path, body=body):
                self.assertEqual(self.client.request(method, path, json=body).status_code, 422)

    def test_missing_resources_return_business_404(self):
        self.login("admin")
        for path in ("/api/books/999", "/api/admin/books/999/copies"):
            self.assertEqual(self.client.get(path).json()["code"], 404)


if __name__ == "__main__":
    unittest.main()
