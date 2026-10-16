import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.common.exceptions import BusinessException
from app.database import Base
from app.models.book_copies import BookCopy
from app.models.books import Book
from app.schemas.book import (
    BookCopyCreateRequest,
    BookCopyUpdateRequest,
    BookCreateRequest,
    BookUpdateRequest,
)
from app.services import book_service


class BookServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)

    def add_book(self, **changes):
        values = {"title": "Python 入门", "author": "测试作者", "category": "计算机"}
        values.update(changes)
        return book_service.create_book(self.db, BookCreateRequest(**values))

    def add_copy(self, book, barcode="LIB-001", status="available"):
        return book_service.create_book_copy(
            self.db,
            BookCopyCreateRequest(
                book_id=book.id, barcode=barcode, location="一楼 A 架", status=status
            ),
        )

    def assert_business_error(self, code, operation):
        with self.assertRaises(BusinessException) as raised:
            operation()
        self.assertEqual(raised.exception.code, code)

    def test_inventory_counts_active_copies_and_hides_unavailable_stock(self):
        book = self.add_book()
        self.add_copy(book)
        self.add_copy(book, "LIB-002", "maintenance")
        self.add_copy(book, "LIB-003", "withdrawn")
        detail = book_service.get_book_detail(self.db, book.id)
        self.assertEqual((detail.total_copies, detail.available_copies), (2, 1))

        book_service.update_book(
            self.db, book.id,
            BookUpdateRequest(title=book.title, author=book.author, is_active=False),
        )
        self.assert_business_error(
            404, lambda: book_service.get_book_detail(self.db, book.id)
        )
        hidden = book_service.get_book_detail(self.db, book.id, active_only=False)
        self.assertEqual((hidden.total_copies, hidden.available_copies), (2, 0))
        self.assertEqual(self.db.query(BookCopy).count(), 3)

    def test_public_list_excludes_inactive_books_and_filters_before_paging(self):
        first = self.add_book(isbn="9787115428028")
        self.add_book(title="算法图解")
        self.add_book(title="Python 旧版", is_active=False)
        self.add_book(title="现代文学", author="Python 作者", category="文学")
        total, items = book_service.list_books_page(
            self.db, 1, 1, keyword="  Python  ", category="计算机"
        )
        self.assertEqual(total, 1)
        self.assertEqual([item.id for item in items], [first.id])
        self.assertEqual(book_service.list_books_page(self.db, 1, 12)[0], 3)
        self.assertEqual(
            book_service.list_books_page(self.db, 1, 12, is_active=None)[0], 4
        )
        self.assertEqual(
            book_service.list_books_page(self.db, 1, 12, is_active=False)[0], 1
        )
        self.assertEqual(
            book_service.list_books_page(self.db, 2, 1, keyword="9787115428028")[1], []
        )

    def test_keyword_search_matches_title_author_isbn_and_escapes_wildcards(self):
        book = self.add_book(title="100% Python", author="王小明", isbn="9787115428028")
        self.add_book(title="1000 Python")
        for keyword in ("100%", "王小", "9787115428028"):
            with self.subTest(keyword=keyword):
                total, items = book_service.list_books_page(self.db, 1, 12, keyword)
                self.assertEqual(total, 1)
                self.assertEqual(items[0].id, book.id)

    def test_duplicate_isbn_create_and_update_leave_session_usable(self):
        self.add_book(isbn="9787115428028")
        second = self.add_book(title="另一书目")
        self.assert_business_error(409, lambda: self.add_book(isbn="9787115428028"))
        self.assert_business_error(
            409,
            lambda: book_service.update_book(
                self.db, second.id,
                BookUpdateRequest(title="冲突", author="测试", isbn="9787115428028"),
            ),
        )
        self.assertEqual(self.db.get(Book, second.id).title, "另一书目")
        self.assertIsNotNone(self.add_book(title="恢复后新增").id)

    def test_update_book_keeps_own_isbn_and_applies_full_replacement(self):
        book = self.add_book(isbn="9787115428028", description="旧简介")
        updated = book_service.update_book(
            self.db, book.id,
            BookUpdateRequest(title="新版", author="作者", isbn=book.isbn),
        )
        self.assertEqual(updated.title, "新版")
        self.assertIsNone(updated.description)

    def test_duplicate_barcode_conflicts_across_books_and_update_is_atomic(self):
        first, second = self.add_book(), self.add_book(title="另一本")
        self.add_copy(first)
        other_copy = self.add_copy(second, "LIB-002")
        self.assert_business_error(409, lambda: self.add_copy(second))
        self.assert_business_error(
            409,
            lambda: book_service.update_book_copy(
                self.db, other_copy.id,
                BookCopyUpdateRequest(barcode="LIB-001", location="二楼"),
            ),
        )
        saved = self.db.get(BookCopy, other_copy.id)
        self.assertEqual((saved.barcode, saved.location), ("LIB-002", "一楼 A 架"))
        self.assertIsNotNone(self.add_copy(second, "LIB-003").id)

    def test_copy_retirement_preserves_record_and_removes_stock(self):
        book = self.add_book()
        copy = self.add_copy(book)
        updated = book_service.update_book_copy(
            self.db, copy.id,
            BookCopyUpdateRequest(barcode=copy.barcode, location="档案库", status="withdrawn"),
        )
        self.assertEqual((updated.id, updated.book_id, updated.status), (copy.id, book.id, "withdrawn"))
        detail = book_service.get_book_detail(self.db, book.id)
        self.assertEqual((detail.total_copies, detail.available_copies), (0, 0))
        total, items = book_service.list_book_copies_page(self.db, book.id, 1, 12)
        self.assertEqual(total, 1)
        self.assertEqual(items[0].location, "档案库")

    def test_missing_books_and_copies_return_404(self):
        operations = (
            lambda: book_service.get_book_detail(self.db, 999),
            lambda: book_service.update_book(self.db, 999, BookUpdateRequest(title="书", author="作者")),
            lambda: book_service.list_book_copies_page(self.db, 999, 1, 12),
            lambda: book_service.create_book_copy(self.db, BookCopyCreateRequest(book_id=999, barcode="MISSING", location="A")),
            lambda: book_service.update_book_copy(self.db, 999, BookCopyUpdateRequest(barcode="MISSING", location="A")),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                self.assert_business_error(404, operation)

    def test_unique_constraint_race_rolls_back_and_allows_next_write(self):
        with patch.object(self.db, "commit", side_effect=IntegrityError("insert", {}, Exception("duplicate"))):
            self.assert_business_error(409, lambda: self.add_book(isbn="9787115428028"))
        self.assertEqual(self.db.query(Book).count(), 0)
        self.assertIsNotNone(self.add_book(isbn="9787115428028").id)
        book = self.db.query(Book).first()
        with patch.object(self.db, "commit", side_effect=IntegrityError("insert", {}, Exception("duplicate"))):
            self.assert_business_error(409, lambda: self.add_copy(book))
        self.assertEqual(self.db.query(BookCopy).count(), 0)
        self.assertIsNotNone(self.add_copy(book).id)


if __name__ == "__main__":
    unittest.main()
