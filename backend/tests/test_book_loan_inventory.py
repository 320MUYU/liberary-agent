import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app.models
from app.common.exceptions import BusinessException
from app.database import Base
from app.models.books import Book
from app.models.book_copies import BookCopy
from app.models.loans import Loan
from app.models.users import User
from app.schemas.book import BookCopyUpdateRequest
from app.services import book_service


class BookLoanInventoryTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')

        @event.listens_for(self.engine, 'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        reader = User(username='inventory-reader', password='unused', name='读者', role='student')
        self.book = Book(title='库存测试', author='作者')
        self.db.add_all([reader, self.book])
        self.db.flush()
        self.copy = BookCopy(book_id=self.book.id, barcode='INV-001', location='一楼')
        self.db.add(self.copy)
        self.db.flush()
        self.loan = Loan(book_id=self.book.id, reader_id=reader.id, open_book_id=self.book.id, status='pending')
        self.db.add(self.loan)
        self.db.commit()

    def borrow(self):
        copy_id = self.copy.id
        self.loan.status = 'borrowed'
        self.loan.copy_id = copy_id
        self.loan.active_copy_id = copy_id
        self.loan.borrowed_at = datetime.now()
        self.loan.due_at = datetime.now() + timedelta(days=30)
        self.db.commit()

    def test_list_and_detail_subtract_only_occupied_copies(self):
        self.assertEqual(book_service.get_book_detail(self.db, self.book.id).available_copies, 1)
        self.borrow()
        detail = book_service.get_book_detail(self.db, self.book.id)
        self.assertEqual((detail.total_copies, detail.available_copies), (1, 0))
        _, items = book_service.list_books_page(self.db, 1, 10)
        self.assertEqual(items[0].available_copies, 0)
        self.loan.status = 'return_pending'
        self.loan.return_requested_at = datetime.now()
        self.db.commit()
        self.assertEqual(book_service.get_book_detail(self.db, self.book.id).available_copies, 0)
        self.loan.status = 'returned'
        self.loan.returned_at = datetime.now()
        self.loan.active_copy_id = None
        self.loan.open_book_id = None
        self.db.commit()
        self.assertEqual(book_service.get_book_detail(self.db, self.book.id).available_copies, 1)

    def test_borrowed_copy_is_marked_and_cannot_be_edited(self):
        self.borrow()
        _, items = book_service.list_book_copies_page(self.db, self.book.id, 1, 10)
        self.assertTrue(items[0].is_on_loan)
        with self.assertRaises(BusinessException) as error:
            book_service.update_book_copy(self.db, self.copy.id, BookCopyUpdateRequest(
                barcode='INV-002', location='二楼', status='maintenance'
            ))
        self.assertEqual(error.exception.code, 409)
        self.assertEqual(self.db.get(BookCopy, self.copy.id).barcode, 'INV-001')

    def test_mysql_decimal_aggregates_are_serialized_as_integer_inventory(self):
        # MySQL SUM(int) returns Decimal; public stock fields must still be JSON numbers.
        with patch.object(book_service, '_inventory', return_value={
            self.book.id: (1, Decimal('1'))
        }):
            payload = book_service.book_response(self.db, self.book).model_dump(mode='json')
        self.assertIs(type(payload['available_copies']), int)
        self.assertEqual(payload['available_copies'], 1)


if __name__ == '__main__':
    unittest.main()
