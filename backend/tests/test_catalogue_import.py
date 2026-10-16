import unittest

from app.models.book_copies import BookCopy
from app.models.books import Book
from app.models.book_sources import BookSource
from app.services.catalogue_import import CatalogueRecord, import_records, records_from_search
from tests import test_book_service as fixtures


def record(**changes):
    values = dict(source_id="/books/OL100M", work_id="/works/OL100W",
                  title="AI Engineering", author="Chip Huyen", isbn="9781098166304",
                  publisher="O'Reilly Media", publication_year=2025, category="AI / Agent",
                  languages=["eng"], subjects=["Artificial intelligence"])
    values.update(changes)
    return CatalogueRecord(**values)


class CatalogueImportTest(unittest.TestCase):
    setUp = fixtures.BookServiceTest.setUp

    def test_import_replay_has_one_book_and_no_invented_copies(self):
        first = import_records(self.db, [record()])
        second = import_records(self.db, [record()])
        self.assertEqual(first[0]["book_id"], second[0]["book_id"])
        self.assertEqual(second[0]["status"], "unchanged")
        self.assertEqual(self.db.query(Book).count(), 1)
        self.assertEqual(self.db.query(BookSource).count(), 1)
        self.assertEqual(self.db.query(BookCopy).count(), 0)
        source = self.db.query(BookSource).one()
        self.assertEqual(source.source_url, "https://openlibrary.org/books/OL100M")
        self.assertEqual(source.metadata_json["languages"], ["eng"])

    def test_preview_does_not_write_and_conflicting_batch_is_atomic(self):
        self.assertEqual(import_records(self.db, [record()], dry_run=True)[0]["status"], "create")
        self.assertEqual(self.db.query(Book).count(), 0)
        with self.assertRaises(ValueError):
            import_records(self.db, [record(), record(source_id="/books/OL101M")])
        self.assertEqual(self.db.query(Book).count(), 0)

    def test_manual_metadata_and_inactive_state_survive_replay(self):
        result = import_records(self.db, [record()])
        book = self.db.get(Book, result[0]["book_id"])
        book.description = "管理员补充说明"
        book.is_active = False
        self.db.commit()
        import_records(self.db, [record()])
        self.assertEqual(book.description, "管理员补充说明")
        self.assertFalse(book.is_active)
        with self.assertRaises(ValueError):
            import_records(self.db, [record(title="Changed source title")])
        self.assertEqual(book.title, "AI Engineering")

    def test_equivalent_isbn10_conflicts_with_existing_manual_book(self):
        self.db.add(Book(title="Existing", author="A", isbn="0134610997"))
        self.db.commit()
        with self.assertRaises(ValueError):
            import_records(self.db, [record(isbn="9780134610993")])
        self.assertEqual(self.db.query(Book).count(), 1)
        self.assertEqual(self.db.query(BookSource).count(), 0)

    def test_invalid_identifiers_and_unexpected_fulltext_are_rejected(self):
        for change in ({"source_id": "https://bad.example/book"}, {"isbn": "9780000000000"},
                       {"fulltext": "not metadata"}, {"author": " "}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                record(**change)

    def test_search_conversion_uses_edition_fields_and_reports_missing_data(self):
        data = {"docs": [{"key": "/works/OL100W", "title": "Work title",
            "author_name": ["A"], "first_publish_year": 1900,
            "isbn": ["9781098166304"], "publisher": ["Wrong publisher"],
            "editions": {"docs": [{"key": "/books/OL100M", "title": "Edition title",
                "language": ["chi"], "publish_date": ["2020"], "publisher": ["Edition publisher"]}]}},
            {"key": "/works/OL101W", "title": "Missing edition"}]}
        records, rejected = records_from_search(data, "历史图书")
        self.assertEqual(len(records), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(records[0].title, "Edition title")
        self.assertEqual(records[0].publication_year, 2020)
        self.assertEqual(records[0].publisher, "Edition publisher")
        self.assertIsNone(records[0].isbn)

    def test_canonical_isbn_and_unknown_date(self):
        item = record(isbn="0-13-461099-7")
        self.assertEqual(item.isbn, "9780134610993")
        data = {"docs": [{"key": "/works/OL100W", "author_name": ["A"],
            "editions": {"docs": [{"key": "/books/OL100M", "title": "Book",
                "publish_date": ["unknown"], "isbn": ["invalid"]}]}}]}
        records, rejected = records_from_search(data, "历史图书")
        self.assertFalse(rejected)
        self.assertIsNone(records[0].isbn)
        self.assertIsNone(records[0].publication_year)

    def test_public_detail_exposes_source_and_keeps_inventory_authoritative(self):
        from app.services import book_service
        book_id = import_records(self.db, [record()])[0]["book_id"]
        detail = book_service.get_book_detail(self.db, book_id)
        self.assertEqual(detail.source.name, "Open Library")
        self.assertEqual(detail.source.languages, ["eng"])
        self.assertEqual(detail.source.url, "https://openlibrary.org/books/OL100M")
        self.assertEqual(detail.total_copies, 0)
        self.db.add(BookCopy(book_id=book_id, barcode="REAL-COPY", location="A1", status="available"))
        self.db.commit()
        self.assertEqual(book_service.get_book_detail(self.db, book_id).available_copies, 1)
        self.assertEqual(book_service.list_books_page(self.db, 1, 10, category="AI / Agent")[0], 1)
