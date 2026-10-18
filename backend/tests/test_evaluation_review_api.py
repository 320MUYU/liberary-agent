import unittest
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.evaluation_review import router
from app.common.exceptions import (
    BusinessException, business_exception_handler, http_exception_handler, validation_exception_handler,
)
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.users import User
from scripts.upgrade_evaluation_reviews import upgrade
from tests.test_evaluation_review import sample_report


class ReviewApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        User.__table__.create(self.engine)
        upgrade(self.engine, apply=True)
        with Session(self.engine) as db:
            db.add(User(id=7, username="admin", name="审核员", password="hash", role="admin"))
            db.commit()
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api")
        for exception, handler in ((HTTPException, http_exception_handler),
                (BusinessException, business_exception_handler), (RequestValidationError, validation_exception_handler)):
            self.app.add_exception_handler(exception, handler)
        def database():
            with Session(self.engine) as db:
                yield db
        self.app.dependency_overrides[get_db] = database
        self.client = TestClient(self.app)
        self.base = "/api/admin/evaluation-reviews"

    def login(self, role="admin"):
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=7, name="审核员", username="admin", role=role)

    def test_every_operation_requires_active_admin(self):
        operations = [("GET", "", {}), ("POST", "/import", {"json": {"name": "测试", "report": sample_report()}}),
            ("GET", "/1", {}), ("GET", "/1/cases/c0:knowledge", {}),
            ("PUT", "/1/cases/c0:knowledge", {"json": {"revision": 0, "status": "draft"}}),
            ("GET", "/1/export/reviews", {}), ("GET", "/1/export/report", {})]
        for role, code in ((None, 401), ("student", 403)):
            if role: self.login(role)
            for method, path, kwargs in operations:
                with self.subTest(role=role, path=path):
                    self.assertEqual(self.client.request(method, self.base + path, **kwargs).status_code, code)

    def test_import_save_reload_conflict_and_export(self):
        self.login()
        response = self.client.post(self.base + "/import", json={"name": "回归", "report": sample_report()}).json()
        self.assertEqual(response["code"], 200)
        path = self.base + f'/{response["data"]["id"]}'
        payload = {"revision": 0, "status": "reviewed", "answer_correct": True, "citations_support": False}
        saved = self.client.put(path + "/cases/c0:knowledge", json=payload).json()["data"]
        self.assertEqual(saved["review"]["reviewer_id"], 7)
        self.assertEqual(self.client.put(path + "/cases/c0:knowledge", json=payload).json()["code"], 409)
        self.assertEqual(self.client.get(path + "/cases/c0:knowledge").json()["data"], saved)
        self.assertEqual(self.client.get(path).json()["data"]["metrics"]["human_reviewed"], 1)
        self.assertEqual(len(self.client.get(path + "/export/reviews").json()["data"]["cases"]), 1)
        self.assertEqual(self.client.get(path + "/export/report").json()["data"]["metrics"]["citation_support_rate"], 0)
        self.assertEqual(self.client.get(path + "?status=bad").status_code, 422)
        self.assertEqual(self.client.get(self.base + "/999999").json()["code"], 404)

    def test_strict_decisions_no_client_identity_and_tampered_import(self):
        self.login()
        path = self.base + "/1/cases/c0:knowledge"
        for payload in ({"revision": 0, "status": "reviewed"},
                {"revision": 0, "answer_correct": "true"}, {"revision": -1},
                {"revision": 0, "reviewer": "forged"}, {"revision": 0, "reviewer_id": 9}):
            self.assertEqual(self.client.put(path, json=payload).status_code, 422)
        report = sample_report()
        report["results"][0]["answer"]["content"] = "tampered"
        self.assertEqual(self.client.post(self.base + "/import", json={"name": "测试", "report": report}).json()["code"], 400)
