import unittest
from datetime import date, datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models
from app.api.admin import router
from app.common.exceptions import http_exception_handler
from app.database import Base, get_db
from app.models.books import Book
from app.models.book_copies import BookCopy
from app.models.evaluation_review import EvaluationRun, EvaluationCaseReview
from app.models.labs import Lab
from app.models.loans import Loan
from app.models.reservations import Reservation
from app.models.users import User
from app.services.admin_tasks import task_summary
from app.utils.jwt import create_access_token


class AdminTasksTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.db.add_all([
            User(id=1, username="admin", name="管理员", password="hash", role="admin"),
            User(id=2, username="reader", name="读者", password="hash", role="student"),
            User(id=3, username="disabled", name="禁用管理员", password="hash", role="admin", status=0),
        ])
        self.db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.add_exception_handler(HTTPException, http_exception_handler)
        def session():
            with Session(self.engine) as db:
                yield db
        app.dependency_overrides[get_db] = session
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_empty_counts_are_zero_and_endpoint_requires_active_admin(self):
        self.assertEqual(task_summary(self.db), {"reservation_pending": 0, "borrow_pending": 0,
            "return_pending": 0, "evaluation_pending": 0, "total": 0})
        path = "/api/admin/tasks/summary"
        self.assertEqual(self.client.get(path).status_code, 401)
        for user_id, status in ((1, 200), (2, 403), (3, 401)):
            response = self.client.get(path, headers={"Authorization": "Bearer " + create_access_token(user_id)})
            self.assertEqual(response.status_code, status)
            if user_id == 1:
                self.assertEqual(response.json()["data"]["total"], 0)

    def add_loan(self, status):
        book = Book(title="待办测试", author="测试")
        self.db.add(book)
        self.db.flush()
        copy = BookCopy(book_id=book.id, barcode=f"COPY-{book.id}", location="测试书架")
        self.db.add(copy)
        self.db.flush()
        borrowed = status in ("borrowed", "return_pending", "returned")
        active = status in ("borrowed", "return_pending")
        requested = status in ("return_pending", "returned")
        now = datetime.now()
        self.db.add(Loan(book_id=book.id, reader_id=2, status=status,
            open_book_id=book.id if status in ("pending", "borrowed", "return_pending") else None,
            copy_id=copy.id if borrowed else None, active_copy_id=copy.id if active else None,
            borrowed_at=now if borrowed else None, due_at=now + timedelta(days=30) if borrowed else None,
            return_requested_at=now if requested else None, returned_at=now if status == "returned" else None))

    def test_full_database_counts_only_actionable_states_and_reflect_changes(self):
        lab = Lab(name="测试空间", code="TEST", building="测试楼", floor="1", capacity=4, category="研讨室")
        self.db.add(lab)
        self.db.flush()
        for status in ("pending", "approved", "rejected", "cancelled"):
            self.db.add(Reservation(lab_id=lab.id, applicant_id=2, date=date.today(), start="10:00", end="11:00",
                purpose="测试", people=2, status=status))
        for _ in range(24):
            self.add_loan("pending")
        for status in ("borrowed", "return_pending", "returned", "rejected", "cancelled"):
            self.add_loan(status)
        run = EvaluationRun(report_id="a" * 64, name="测试", payload={}, imported_by=1)
        self.db.add(run)
        self.db.flush()
        for status in ("pending_human", "draft", "reviewed"):
            self.db.add(EvaluationCaseReview(run_id=run.id, case_id=status, status=status))
        self.db.commit()
        self.assertEqual(task_summary(self.db), {"reservation_pending": 1, "borrow_pending": 24,
            "return_pending": 1, "evaluation_pending": 2, "total": 28})
        self.db.query(EvaluationCaseReview).filter_by(status="draft").update({"status": "reviewed"})
        self.db.query(Reservation).filter_by(status="pending").update({"status": "rejected"})
        self.db.commit()
        self.assertEqual(task_summary(self.db)["total"], 26)
