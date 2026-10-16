import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.common.exceptions import BusinessException
from app.database import Base
from app.models.book_copies import BookCopy
from app.models.books import Book
from app.models.loans import Loan
from app.models.users import User
from app.schemas.loan import BorrowConfirmRequest, LoanRejectRequest, LoanRequest
from app.services import loan_service


class LoanServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.reader = User(username="reader", password="hash", name="读者甲", role="student")
        self.other = User(username="other", password="hash", name="读者乙", role="student")
        self.admin = User(username="admin", password="hash", name="管理员", role="admin")
        self.db.add_all([self.reader, self.other, self.admin])
        self.book, self.copy = self.add_book()
        self.db.commit()

    def add_book(self, title="Python 入门", barcode="LIB-1", **changes):
        book = Book(title=title, author="作者", **changes)
        self.db.add(book)
        self.db.flush()
        copy = BookCopy(book_id=book.id, barcode=barcode, location="一楼 A 架")
        self.db.add(copy)
        self.db.flush()
        return book, copy

    def apply(self, reader=None, book=None):
        return loan_service.create_loan(
            self.db, reader or self.reader, LoanRequest(book_id=(book or self.book).id)
        )

    def borrow(self, loan, copy_id=None):
        return loan_service.confirm_borrow(
            self.db, self.admin, loan.id, BorrowConfirmRequest(copy_id=copy_id)
        )

    def assert_business_error(self, code, action):
        with self.assertRaises(BusinessException) as caught:
            action()
        self.assertEqual(caught.exception.code, code)
        self.assertFalse(self.db.in_transaction(), "业务失败后必须释放事务与行锁")

    def test_complete_flow_retains_historical_copy_and_releases_inventory(self):
        loan = self.apply()
        self.assertEqual(loan.status, "pending")
        self.assertIsNone(loan.active_copy_id)
        borrowed = self.borrow(loan)
        self.assertEqual(borrowed.status, "borrowed")
        self.assertEqual(borrowed.active_copy_id, self.copy.id)
        self.assertEqual(borrowed.copy_id, self.copy.id)
        self.assertEqual(borrowed.borrowed_by, self.admin.id)
        self.assertEqual(borrowed.due_at - borrowed.borrowed_at, timedelta(days=30))
        requested = loan_service.request_return(self.db, self.reader, loan.id)
        self.assertEqual(requested.status, "return_pending")
        self.assertEqual(requested.active_copy_id, self.copy.id)
        self.assertIsNotNone(requested.return_requested_at)
        returned = loan_service.confirm_return(self.db, self.admin, loan.id)
        self.assertEqual(returned.status, "returned")
        self.assertEqual(returned.copy_id, self.copy.id)
        self.assertIsNone(returned.active_copy_id)
        self.assertIsNone(returned.open_book_id)
        self.assertEqual(returned.returned_by, self.admin.id)
        self.assertIsNotNone(returned.returned_at)
        self.assertNotEqual(self.apply().id, loan.id)

    def test_applications_do_not_reserve_copy_and_confirm_rechecks_inventory(self):
        first = self.apply()
        second = self.apply(self.other)
        self.assertIsNone(first.active_copy_id)
        self.assertIsNone(second.active_copy_id)
        self.borrow(first)
        self.assert_business_error(409, lambda: self.borrow(second))
        self.assertEqual(self.db.get(Loan, second.id).status, "pending")

    def test_duplicate_open_application_rejected_and_cancel_allows_new_one(self):
        first = self.apply()
        self.assert_business_error(409, lambda: self.apply())
        cancelled = loan_service.cancel_loan(self.db, self.reader, first.id)
        self.assertEqual(cancelled.status, "cancelled")
        self.assertIsNone(cancelled.open_book_id)
        self.assertNotEqual(self.apply().id, first.id)

    def test_other_reader_cannot_cancel_or_request_return(self):
        loan = self.apply()
        self.assert_business_error(
            404, lambda: loan_service.cancel_loan(self.db, self.other, loan.id)
        )
        self.borrow(loan)
        self.assert_business_error(
            404, lambda: loan_service.request_return(self.db, self.other, loan.id)
        )

    def test_disabled_reader_and_inactive_book_block_confirm(self):
        loan = self.apply()
        self.reader.status = 0
        self.db.commit()
        self.assert_business_error(409, lambda: self.borrow(loan))
        self.reader.status = 1
        self.book.is_active = False
        self.db.commit()
        self.assert_business_error(409, lambda: self.borrow(loan))

    def test_inactive_or_unavailable_book_cannot_be_requested(self):
        self.book.is_active = False
        self.db.commit()
        self.assert_business_error(404, lambda: self.apply())
        self.book.is_active = True
        self.copy.status = "maintenance"
        self.db.commit()
        self.assert_business_error(409, lambda: self.apply())
        self.copy.status = "withdrawn"
        self.db.commit()
        self.assert_business_error(409, lambda: self.apply())

    def test_confirm_checks_copy_belongs_to_book_and_available_status(self):
        second_book, foreign_copy = self.add_book("算法", "LIB-2")
        self.db.commit()
        loan = self.apply()
        self.assert_business_error(409, lambda: self.borrow(loan, foreign_copy.id))
        self.copy.status = "maintenance"
        self.db.commit()
        self.assert_business_error(409, lambda: self.borrow(loan, self.copy.id))
        self.assert_business_error(409, lambda: self.borrow(loan, 99999))

    def test_limit_counts_return_requests_but_not_pending_applications(self):
        loans = []
        for number in range(6):
            book, _ = self.add_book(f"图书 {number}", f"LIMIT-{number}")
            self.db.commit()
            loans.append(self.apply(book=book))
        for loan in loans[:5]:
            self.borrow(loan)
        loan_service.request_return(self.db, self.reader, loans[0].id)
        self.assert_business_error(409, lambda: self.borrow(loans[5]))
        loan_service.confirm_return(self.db, self.admin, loans[0].id)
        self.assertEqual(self.borrow(loans[5]).status, "borrowed")

    def test_reject_records_admin_reason_and_allows_another_application(self):
        loan = self.apply()
        rejected = loan_service.reject_loan(
            self.db, self.admin, loan.id, LoanRejectRequest(reason="馆藏盘点")
        )
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.reviewed_by, self.admin.id)
        self.assertEqual(rejected.reject_reason, "馆藏盘点")
        self.assertIsNone(rejected.open_book_id)
        self.assertNotEqual(self.apply().id, loan.id)

    def test_invalid_state_transitions_conflict(self):
        loan = self.apply()
        self.assert_business_error(
            409, lambda: loan_service.request_return(self.db, self.reader, loan.id)
        )
        self.assert_business_error(
            409, lambda: loan_service.confirm_return(self.db, self.admin, loan.id)
        )
        self.borrow(loan)
        self.assert_business_error(409, lambda: self.borrow(loan))
        self.assert_business_error(
            409, lambda: loan_service.cancel_loan(self.db, self.reader, loan.id)
        )
        self.assert_business_error(
            409,
            lambda: loan_service.reject_loan(
                self.db, self.admin, loan.id, LoanRejectRequest(reason="重复审核")
            ),
        )
        loan_service.request_return(self.db, self.reader, loan.id)
        self.assert_business_error(
            409, lambda: loan_service.request_return(self.db, self.reader, loan.id)
        )
        loan_service.confirm_return(self.db, self.admin, loan.id)
        self.assert_business_error(
            409, lambda: loan_service.confirm_return(self.db, self.admin, loan.id)
        )

    def test_missing_loan_has_no_information_leak(self):
        self.assert_business_error(
            404, lambda: loan_service.cancel_loan(self.db, self.reader, 9999)
        )
        self.assert_business_error(
            404, lambda: loan_service.confirm_borrow(
                self.db, self.admin, 9999, BorrowConfirmRequest()
            )
        )

    def test_list_pagination_owner_filter_keyword_and_history_preview(self):
        own = self.apply()
        other = self.apply(self.other)
        self.borrow(own)
        own.borrowed_at = datetime.now() - timedelta(days=31)
        own.due_at = datetime.now() - timedelta(seconds=1)
        self.db.commit()
        total, items = loan_service.list_my_loans(self.db, self.reader, 1, 1, "borrowed")
        self.assertEqual(total, 1)
        self.assertEqual(items[0].id, own.id)
        self.assertTrue(items[0].is_overdue)
        self.assertEqual(items[0].barcode, self.copy.barcode)
        self.assertEqual(items[0].location, self.copy.location)
        self.assertEqual(items[0].book_title, self.book.title)
        self.assertEqual(items[0].reader_username, self.reader.username)
        total, items = loan_service.list_loans_page(self.db, 1, 10, "pending", "读者乙")
        self.assertEqual(total, 1)
        self.assertEqual(items[0].id, other.id)
        total, _ = loan_service.list_loans_page(self.db, 1, 10, None, "Python")
        self.assertEqual(total, 2)
        total, items = loan_service.list_loans_page(self.db, 3, 1, None, None)
        self.assertEqual(total, 2)
        self.assertEqual(items, [])

    def test_invalid_status_filter_is_rejected(self):
        with self.assertRaises(BusinessException) as caught:
            loan_service.list_my_loans(self.db, self.reader, 1, 10, "deleted")
        self.assertEqual(caught.exception.code, 400)

    def test_failed_commit_rolls_back_and_surfaces_integrity_conflict(self):
        self.db.commit()
        with patch.object(self.db, "commit", side_effect=IntegrityError("insert", {}, Exception())):
            self.assert_business_error(409, lambda: self.apply())
        self.assertEqual(self.db.query(Loan).count(), 0)

    def test_database_operational_failure_is_rolled_back_and_not_hidden(self):
        self.db.commit()
        with patch.object(self.db, "commit", side_effect=OperationalError("insert", {}, Exception())):
            with self.assertRaises(OperationalError):
                self.apply()
        self.assertFalse(self.db.in_transaction())
        self.assertEqual(self.db.query(Loan).count(), 0)

    def test_mysql_deadlock_and_lock_timeout_roll_back_as_retryable_conflicts(self):
        for mysql_code in (1213, 1205):
            with self.subTest(mysql_code=mysql_code):
                self.db.commit()
                error = OperationalError("insert", {}, Exception(mysql_code, "lock conflict"))
                with patch.object(self.db, "commit", side_effect=error):
                    self.assert_business_error(409, lambda: self.apply())
                self.assertEqual(self.db.query(Loan).count(), 0)


if __name__ == "__main__":
    unittest.main()
