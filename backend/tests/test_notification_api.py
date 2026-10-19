"""Reader inbox ownership, durable read state and bounded bulk actions."""

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models
from app.database import Base, get_db
from app.main import app
from app.models.notification import Notification
from app.models.users import User
from app.models.books import Book
from app.models.loans import Loan
from app.utils.jwt import create_access_token


class NotificationApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            db.add_all([User(id=i, username=f"reader{i}", password="hash", name="读者", role="student") for i in (1, 2)])
            db.commit()
        def session():
            with Session(self.engine) as db:
                yield db
        overrides = app.dependency_overrides.copy()
        app.dependency_overrides[get_db] = session
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(overrides)))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": "Bearer " + create_access_token(1)}

    def notice(self, user=1, key="loan:1:borrowed"):
        with Session(self.engine) as db:
            notice = Notification(user_id=user, event_key=key, kind="loan_borrowed", title="已确认借出",
                content="《测试图书》已借出", resource_type="loan", resource_id=1)
            db.add(notice)
            db.commit()
            return notice.id

    def get(self, **params):
        response = self.client.get("/api/notifications", headers=self.headers, params=params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 200)
        return response.json()["data"]

    def test_all_endpoints_require_authentication(self):
        for method, path, kwargs in (("GET", "", {}), ("POST", "/1/read", {}),
                ("POST", "/read-all", {"json": {"through_id": 1}})):
            with self.subTest(path=path):
                self.assertEqual(self.client.request(method, "/api/notifications" + path, **kwargs).status_code, 401)

    def test_loan_deep_link_reads_current_owned_record_outside_list_page(self):
        with Session(self.engine) as db:
            book = Book(title='详情图书', author='作者')
            db.add(book)
            db.flush()
            own = Loan(reader_id=1, book_id=book.id, status='rejected', reject_reason='已处理')
            other = Loan(reader_id=2, book_id=book.id, status='cancelled')
            db.add_all([own, other])
            db.commit()
            own_id, other_id = own.id, other.id
        response = self.client.get(f'/api/loans/{own_id}', headers=self.headers).json()
        self.assertEqual(response['data']['reject_reason'], '已处理')
        for target in (other_id, 99999):
            self.assertEqual(self.client.get(f'/api/loans/{target}', headers=self.headers).json()['code'], 404)
        self.assertEqual(self.client.get(f'/api/loans/{own_id}').status_code, 401)

    def test_list_is_owned_paginated_and_newest_first(self):
        first = self.notice()
        second = self.notice(key="loan:2:borrowed")
        self.notice(user=2)
        listing = self.get(page_size=1)
        self.assertEqual((listing["total"], listing["unread_count"], listing["max_id"]), (2, 2, second))
        self.assertEqual([n["id"] for n in listing["items"]], [second])
        self.assertEqual(self.get(page=2, page_size=1)["items"][0]["id"], first)
        self.assertNotIn("user_id", listing["items"][0])
        self.assertNotIn("event_key", listing["items"][0])

    def test_mark_read_is_durable_idempotent_and_cannot_touch_other_user(self):
        own, other = self.notice(), self.notice(user=2)
        path = f"/api/notifications/{own}/read"
        first = self.client.post(path, headers=self.headers).json()
        self.assertEqual(first["code"], 200)
        self.assertIsNotNone(first["data"]["read_at"])
        replay = self.client.post(path, headers=self.headers).json()
        self.assertEqual(first["data"]["read_at"], replay["data"]["read_at"])
        self.assertEqual(self.get(unread_only=True)["total"], 0)
        self.assertEqual(self.get()["unread_count"], 0)
        for target in (other, 9999):
            self.assertEqual(self.client.post(f"/api/notifications/{target}/read", headers=self.headers).json()["code"], 404)
        with Session(self.engine) as db:
            self.assertIsNone(db.get(Notification, other).read_at)

    def test_bulk_read_respects_snapshot_boundary_and_user(self):
        first, other = self.notice(), self.notice(user=2)
        boundary = self.get()["max_id"]
        later = self.notice(key="loan:3:borrowed")
        for expected in (1, 0):
            result = self.client.post("/api/notifications/read-all", headers=self.headers,
                json={"through_id": boundary}).json()
            self.assertEqual(result["code"], 200)
            self.assertEqual(result["data"]["updated"], expected)
        self.assertEqual([n["id"] for n in self.get(unread_only=True)["items"]], [later])
        with Session(self.engine) as db:
            self.assertIsNotNone(db.get(Notification, first).read_at)
            self.assertIsNone(db.get(Notification, other).read_at)

    def test_invalid_pagination_and_unbounded_bulk_read_are_rejected(self):
        for params in ({"page": 0}, {"page_size": 101}, {"unread_only": "invalid"}):
            self.assertEqual(self.client.get("/api/notifications", headers=self.headers, params=params).status_code, 422)
        for body in ({}, {"through_id": -1}):
            self.assertEqual(self.client.post("/api/notifications/read-all", headers=self.headers, json=body).status_code, 422)

