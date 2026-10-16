import unittest
from datetime import datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models
from app.database import Base
from app.models.books import Book
from app.models.book_copies import BookCopy
from app.models.loans import Loan
from app.models.users import User
from app.schemas.loan import BorrowConfirmRequest, LoanRejectRequest, LoanRequest


class LoanModelsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')

        @event.listens_for(self.engine, 'connect')
        def enable_foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.reader = User(username='reader', password='unused', name='读者', role='student')
        self.other = User(username='other', password='unused', name='其他读者', role='student')
        self.admin = User(username='admin', password='unused', name='管理员', role='admin')
        self.book = Book(title='实体图书', author='测试作者')
        self.db.add_all([self.reader, self.other, self.admin, self.book])
        self.db.flush()
        self.copy = BookCopy(book_id=self.book.id, barcode='TEST-001', location='一楼')
        self.db.add(self.copy)
        self.db.commit()

    def loan(self, **changes):
        values = dict(book_id=self.book.id, reader_id=self.reader.id,
                      open_book_id=self.book.id, status='pending')
        values.update(changes)
        result = Loan(**values)
        self.db.add(result)
        self.db.flush()
        return result

    def borrowed(self, **changes):
        now = datetime.now()
        values = dict(status='borrowed', copy_id=self.copy.id,
                      active_copy_id=self.copy.id, borrowed_at=now,
                      due_at=now + timedelta(days=30), borrowed_by=self.admin.id)
        values.update(changes)
        return self.loan(**values)

    def test_model_is_registered_and_new_table_creation_preserves_catalogue(self):
        self.assertIn('book_loans', Base.metadata.tables)
        Base.metadata.create_all(self.engine)
        self.assertIn('book_loans', inspect(self.engine).get_table_names())
        self.assertEqual(self.db.get(BookCopy, self.copy.id).barcode, 'TEST-001')

    def test_pending_application_does_not_occupy_a_copy(self):
        first = self.loan()
        second = self.loan(reader_id=self.other.id)
        self.db.commit()
        self.assertIsNone(first.active_copy_id)
        self.assertIsNone(second.copy_id)
        self.assertIsNotNone(first.create_time)

    def test_reader_cannot_have_two_unfinished_applications_for_same_book(self):
        self.loan()
        self.db.commit()
        with self.assertRaises(IntegrityError):
            self.loan()
        self.db.rollback()
        self.assertEqual(self.db.query(Loan).count(), 1)

    def test_same_copy_cannot_be_occupied_by_two_readers(self):
        self.borrowed()
        self.db.commit()
        with self.assertRaises(IntegrityError):
            self.borrowed(reader_id=self.other.id)
        self.db.rollback()

    def test_return_application_keeps_copy_occupied(self):
        first = self.borrowed()
        first.status = 'return_pending'
        first.return_requested_at = datetime.now()
        self.db.commit()
        with self.assertRaises(IntegrityError):
            self.borrowed(reader_id=self.other.id)
        self.db.rollback()

    def test_confirmed_return_releases_copy_but_preserves_history(self):
        first = self.borrowed()
        first.status = 'returned'
        first.return_requested_at = datetime.now()
        first.returned_at = datetime.now()
        first.returned_by = self.admin.id
        first.active_copy_id = None
        first.open_book_id = None
        self.db.commit()
        next_loan = self.borrowed(reader_id=self.other.id)
        self.db.commit()
        self.assertEqual(first.copy_id, next_loan.copy_id)

    def test_invalid_state_or_inconsistent_occupancy_is_rejected(self):
        for changes in [dict(status='unknown'), dict(status='cancelled'),
                        dict(open_book_id=None), dict(active_copy_id=self.copy.id),
                        dict(status='borrowed')]:
            with self.subTest(changes=changes):
                with self.assertRaises(IntegrityError):
                    self.loan(**changes)
                self.db.rollback()

    def test_missing_reader_or_book_is_rejected(self):
        for changes in [dict(reader_id=99999), dict(book_id=99999, open_book_id=99999)]:
            with self.subTest(changes=changes):
                with self.assertRaises(IntegrityError):
                    self.loan(**changes)
                self.db.rollback()

    def test_completed_requests_allow_a_new_application(self):
        self.loan(status='cancelled', open_book_id=None)
        self.loan(status='rejected', open_book_id=None, reject_reason='测试拒绝')
        self.loan()
        self.db.commit()
        self.assertEqual(self.db.query(Loan).count(), 3)


class LoanSchemasTest(unittest.TestCase):
    def test_ids_are_strict_positive_and_cannot_choose_reader_or_state(self):
        for value in [0, -1, True, '1']:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    LoanRequest(book_id=value)
                with self.assertRaises(ValidationError):
                    BorrowConfirmRequest(copy_id=value)
        for field in ['reader_id', 'status', 'due_at']:
            with self.assertRaises(ValidationError):
                LoanRequest(book_id=1, **{field: 2})
        self.assertIsNone(BorrowConfirmRequest().copy_id)

    def test_rejection_requires_a_bounded_nonblank_reason(self):
        self.assertEqual(LoanRejectRequest(reason='  暂不符合要求  ').reason, '暂不符合要求')
        for reason in ['', '  ', '字' * 501]:
            with self.assertRaises(ValidationError):
                LoanRejectRequest(reason=reason)


if __name__ == '__main__':
    unittest.main()
