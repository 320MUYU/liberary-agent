import unittest

from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.database import Base
from app.models.book_copies import BookCopy
from app.models.books import Book
from app.models.users import User


class BookModelsTest(unittest.TestCase):
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
        values = {"title": "Python 编程入门", "author": "测试作者", "category": "计算机"}
        values.update(changes)
        book = Book(**values)
        self.db.add(book)
        self.db.flush()
        return book

    def add_copy(self, book, **changes):
        values = {"book_id": book.id, "barcode": "LIB-0001", "location": "一楼 A 架"}
        values.update(changes)
        copy = BookCopy(**values)
        self.db.add(copy)
        self.db.flush()
        return copy

    def test_multiple_copies_keep_their_own_locations_and_states(self):
        book = self.add_book()
        available = self.add_copy(book)
        maintenance = self.add_copy(
            book, barcode="LIB-0002", location="二楼 B 架", status="maintenance"
        )
        self.db.commit()
        self.db.expire_all()

        saved = self.db.get(Book, book.id)
        self.assertTrue(saved.is_active)
        self.assertEqual(saved.isbn, None)
        self.assertEqual({copy.id for copy in saved.copies}, {available.id, maintenance.id})
        self.assertEqual(available.status, "available")
        self.assertEqual(maintenance.location, "二楼 B 架")
        self.assertEqual(maintenance.book.id, saved.id)
        self.assertIsNotNone(saved.create_time)

    def test_duplicate_isbn_is_rejected_and_transaction_can_recover(self):
        first = self.add_book(isbn="9787115428028")
        self.db.commit()
        first_id = first.id

        with self.assertRaises(IntegrityError):
            self.add_book(title="重复 ISBN", isbn="9787115428028")
        self.db.rollback()

        second = self.add_book(title="其他书目", isbn="9780306406157")
        self.db.commit()
        self.assertIsNotNone(self.db.get(Book, first_id))
        self.assertNotEqual(second.id, first_id)

    def test_books_without_isbn_can_coexist(self):
        first = self.add_book()
        second = self.add_book(title="图书馆使用手册")
        self.db.commit()
        self.assertNotEqual(first.id, second.id)

    def test_barcode_is_unique_across_books(self):
        first = self.add_book()
        second = self.add_book(title="算法入门")
        self.add_copy(first)
        self.db.commit()

        with self.assertRaises(IntegrityError):
            self.add_copy(second)
        self.db.rollback()

    def test_copy_cannot_reference_missing_book(self):
        self.db.add(BookCopy(book_id=999, barcode="LIB-UNKNOWN", location="一楼 A 架"))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_book_with_copies_cannot_be_deleted(self):
        book = self.add_book()
        copy = self.add_copy(book)
        self.db.commit()
        book_id, copy_id = book.id, copy.id

        self.db.delete(book)
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

        self.assertIsNotNone(self.db.get(Book, book_id))
        self.assertIsNotNone(self.db.get(BookCopy, copy_id))

    def test_deactivating_book_preserves_copies(self):
        book = self.add_book()
        self.add_copy(book)
        self.db.commit()
        book.is_active = False
        self.db.commit()
        self.db.expire_all()

        saved = self.db.get(Book, book.id)
        self.assertFalse(saved.is_active)
        self.assertEqual(len(saved.copies), 1)

    def test_invalid_copy_state_is_rejected_by_database(self):
        book = self.add_book()
        self.db.commit()
        with self.assertRaises(IntegrityError):
            self.add_copy(book, status="invented")
        self.db.rollback()

    def test_withdrawing_copy_preserves_barcode_and_location(self):
        book = self.add_book()
        copy = self.add_copy(book)
        self.db.commit()
        copy.status = "withdrawn"
        self.db.commit()
        self.db.expire_all()

        saved = self.db.get(BookCopy, copy.id)
        self.assertEqual(saved.status, "withdrawn")
        self.assertEqual(saved.barcode, "LIB-0001")
        self.assertEqual(saved.location, "一楼 A 架")

    def test_creating_new_tables_and_repeating_creation_preserves_existing_data(self):
        legacy_engine = create_engine("sqlite:///:memory:")
        self.addCleanup(legacy_engine.dispose)
        User.__table__.create(legacy_engine)
        with Session(legacy_engine) as legacy_db:
            user = User(
                username="existing-reader", password="hash", name="已有读者", role="student"
            )
            legacy_db.add(user)
            legacy_db.commit()

        Base.metadata.create_all(legacy_engine)
        with Session(legacy_engine) as legacy_db:
            book = Book(title="新增图书", author="测试作者", category="计算机")
            legacy_db.add(book)
            legacy_db.commit()

        Base.metadata.create_all(legacy_engine)
        with Session(legacy_engine) as legacy_db:
            self.assertEqual(legacy_db.scalar(select(User)).username, "existing-reader")
            self.assertEqual(legacy_db.scalar(select(Book)).title, "新增图书")
        self.assertTrue({"books", "book_copies"}.issubset(inspect(legacy_engine).get_table_names()))


if __name__ == "__main__":
    unittest.main()
