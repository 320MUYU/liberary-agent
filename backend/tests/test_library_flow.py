"""Exercise real auth, catalogue and circulation together without cloud services."""

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models
from app.database import Base, get_db
from app.main import app
from app.models.users import User
from app.utils.bcrypt import hash_password


class LibraryFlowTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        with Session(self.engine) as db:
            password = hash_password("LibraryFlow123")
            for username, role in [("admin", "admin"), ("reader", "student"), ("other", "student")]:
                db.add(User(username=username, password=password, name=username, role=role))
            db.commit()

        def session():
            with Session(self.engine) as db:
                yield db

        overrides = app.dependency_overrides.copy()
        app.dependency_overrides[get_db] = session
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(overrides)))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {}
        for username in ["admin", "reader", "other"]:
            login = self.client.post("/api/auth/login", json={"username": username, "password": "LibraryFlow123"})
            self.assertEqual(login.json()["code"], 200)
            self.headers[username] = {"Authorization": "Bearer " + login.json()["data"]["token"]}

    def request(self, method, path, role="admin", **kwargs):
        response = self.client.request(method, "/api" + path, headers=self.headers[role], **kwargs)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["code"], 200, response.text)
        return response.json()["data"]

    def catalogue(self):
        book = self.request("POST", "/admin/books", json={"title": "测试图书", "author": "作者", "category": "文学"})
        copy = self.request("POST", "/admin/book-copies", json={
            "book_id": book["id"], "barcode": "FLOW-001", "location": "二楼 A 架"
        })
        return book, copy

    def test_complete_two_reader_flow_restores_actual_inventory(self):
        book, copy = self.catalogue()
        bid = book["id"]
        listing = self.request("GET", "/books", role="reader", params={"keyword": "测试", "category": "文学"})
        self.assertEqual(listing["items"][0]["available_copies"], 1)
        first = self.request("POST", "/loans", role="reader", json={"book_id": bid})
        second = self.request("POST", "/loans", role="other", json={"book_id": bid})
        self.assertEqual(self.request("GET", f"/books/{bid}", role="reader")["available_copies"], 1)
        self.assertIsNone(first["copy_id"])
        first = self.request("POST", f"/admin/loans/{first['id']}/confirm-borrow", json={"copy_id": copy["id"]})
        self.assertEqual(first["barcode"], "FLOW-001")
        self.assertEqual(first["status"], "borrowed")
        self.assertEqual(self.request("GET", f"/books/{bid}", role="reader")["available_copies"], 0)
        conflict = self.client.post(f"/api/admin/loans/{second['id']}/confirm-borrow", headers=self.headers["admin"], json={})
        self.assertEqual(conflict.json()["code"], 409)
        copies = self.request("GET", f"/admin/books/{bid}/copies")
        self.assertTrue(copies["items"][0]["is_on_loan"])
        self.request("POST", f"/loans/{first['id']}/request-return", role="reader")
        self.assertEqual(self.request("GET", f"/books/{bid}", role="reader")["available_copies"], 0)
        returned = self.request("POST", f"/admin/loans/{first['id']}/confirm-return")
        self.assertEqual(returned["status"], "returned")
        self.assertEqual(returned["copy_id"], copy["id"])
        self.assertEqual(self.request("GET", f"/books/{bid}", role="reader")["available_copies"], 1)
        self.request("POST", f"/admin/loans/{second['id']}/confirm-borrow", json={})
        mine = self.request("GET", "/loans", role="reader")
        self.assertEqual(mine["total"], 1)
        self.assertEqual(mine["items"][0]["status"], "returned")
        self.assertNotEqual(mine["items"][0]["reader_id"], second["reader_id"])

    def test_real_auth_blocks_reader_admin_actions_and_other_readers_requests(self):
        self.assertEqual(self.client.get("/api/books").status_code, 401)
        book, _ = self.catalogue()
        self.assertEqual(self.client.get("/api/admin/books", headers=self.headers["reader"]).status_code, 403)
        first = self.request("POST", "/loans", role="reader", json={"book_id": book["id"]})
        for suffix in ["cancel", "request-return"]:
            result = self.client.post(f"/api/loans/{first['id']}/{suffix}", headers=self.headers["other"])
            self.assertIn(result.json()["code"], [403, 404])
        forbidden = self.client.post(f"/api/admin/loans/{first['id']}/confirm-borrow", headers=self.headers["reader"], json={})
        self.assertEqual(forbidden.status_code, 403)
        self.request("POST", f"/loans/{first['id']}/cancel", role="reader")
        again = self.request("POST", "/loans", role="reader", json={"book_id": book["id"]})
        rejected = self.request("POST", f"/admin/loans/{again['id']}/reject", json={"reason": "演示拒绝"})
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["reject_reason"], "演示拒绝")


if __name__ == "__main__":
    unittest.main()
