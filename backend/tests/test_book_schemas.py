import unittest
from types import SimpleNamespace

from pydantic import ValidationError

from app.schemas.book import (
    BookCopyCreateRequest,
    BookCopyPageResponse,
    BookCopyResponse,
    BookCopyUpdateRequest,
    BookCreateRequest,
    BookPageResponse,
    BookResponse,
    BookUpdateRequest,
)


class BookRequestTest(unittest.TestCase):
    def request(self, schema=BookCreateRequest, **changes):
        values = {"title": "Python 编程入门", "author": "测试作者"}
        values.update(changes)
        return schema(**values)

    def test_required_text_is_trimmed_and_defaults_are_ready_for_catalogue(self):
        for schema in (BookCreateRequest, BookUpdateRequest):
            with self.subTest(schema=schema.__name__):
                request = self.request(
                    schema, title="  Python 编程入门\n", author="\t测试作者  "
                )
                self.assertEqual(request.title, "Python 编程入门")
                self.assertEqual(request.author, "测试作者")
                self.assertEqual(request.category, "未分类")
                self.assertTrue(request.is_active)
                self.assertIsNone(request.isbn)
                self.assertIsNone(request.publication_year)
                self.assertIsNone(request.publisher)
                self.assertIsNone(request.description)
                self.assertIsNone(request.cover)

    def test_create_and_full_update_require_title_and_author(self):
        for schema in (BookCreateRequest, BookUpdateRequest):
            for field in ("title", "author"):
                with self.subTest(schema=schema.__name__, field=field):
                    values = {"title": "Python 编程入门", "author": "测试作者"}
                    del values[field]
                    with self.assertRaises(ValidationError):
                        schema(**values)

    def test_required_text_and_category_cannot_be_blank(self):
        for schema in (BookCreateRequest, BookUpdateRequest):
            for field in ("title", "author", "category"):
                for value in ("", " \t\n "):
                    with self.subTest(schema=schema.__name__, field=field, value=value):
                        with self.assertRaises(ValidationError):
                            self.request(schema, **{field: value})

    def test_isbn_normalization_supports_valid_isbn10_and_isbn13(self):
        cases = (
            ("9787115428028", "9787115428028"),
            (" 978-7-115-42802-8\n", "9787115428028"),
            ("0-306-40615-2", "0306406152"),
            (" 0 8044 2957 x ", "080442957X"),
        )
        for schema in (BookCreateRequest, BookUpdateRequest):
            for value, expected in cases:
                with self.subTest(schema=schema.__name__, isbn=value):
                    self.assertEqual(self.request(schema, isbn=value).isbn, expected)

    def test_missing_or_blank_isbn_is_optional(self):
        for schema in (BookCreateRequest, BookUpdateRequest):
            for value in (None, "", " \t\n "):
                with self.subTest(schema=schema.__name__, isbn=value):
                    self.assertIsNone(self.request(schema, isbn=value).isbn)

    def test_isbn_rejects_wrong_length_characters_or_checksum(self):
        invalid = (
            "123456789",
            "12345678901",
            "97871154280288",
            "9787115428029",
            "0306406153",
            "0804429570",
            "X804429570",
            "978711542802X",
            "978711542802A",
            "978.7115428028",
        )
        for schema in (BookCreateRequest, BookUpdateRequest):
            for value in invalid:
                with self.subTest(schema=schema.__name__, isbn=value):
                    with self.assertRaises(ValidationError):
                        self.request(schema, isbn=value)

    def test_publication_year_accepts_null_and_calendar_year_boundaries(self):
        for schema in (BookCreateRequest, BookUpdateRequest):
            for year in (None, 1, 2024, 9999):
                with self.subTest(schema=schema.__name__, year=year):
                    self.assertEqual(self.request(schema, publication_year=year).publication_year, year)

    def test_publication_year_rejects_out_of_range_and_boolean_values(self):
        for schema in (BookCreateRequest, BookUpdateRequest):
            for year in (0, -1, 10000, True, False, 2024.5):
                with self.subTest(schema=schema.__name__, year=year):
                    with self.assertRaises(ValidationError):
                        self.request(schema, publication_year=year)

    def test_active_flag_requires_an_actual_boolean(self):
        for schema in (BookCreateRequest, BookUpdateRequest):
            with self.subTest(schema=schema.__name__, active=False):
                self.assertFalse(self.request(schema, is_active=False).is_active)
            for active in (0, 1, "true", "false", None):
                with self.subTest(schema=schema.__name__, active=active):
                    with self.assertRaises(ValidationError):
                        self.request(schema, is_active=active)

    def test_clients_cannot_supply_derived_stock_counts(self):
        for schema in (BookCreateRequest, BookUpdateRequest):
            for field in ("total_copies", "available_copies", "stock"):
                with self.subTest(schema=schema.__name__, field=field):
                    with self.assertRaises(ValidationError):
                        self.request(schema, **{field: 3})


class BookCopyRequestTest(unittest.TestCase):
    def create(self, **changes):
        values = {"book_id": 1, "barcode": "LIB-0001", "location": "二楼 A-01"}
        values.update(changes)
        return BookCopyCreateRequest(**values)

    def update(self, **changes):
        values = {"barcode": "LIB-0001", "location": "二楼 A-01"}
        values.update(changes)
        return BookCopyUpdateRequest(**values)

    def test_registration_trims_barcode_and_location_and_defaults_to_available(self):
        for request in (self.create, self.update):
            with self.subTest(operation=request.__name__):
                result = request(barcode="  LIB-0001\n", location="\t二楼 A-01  ")
                self.assertEqual(result.barcode, "LIB-0001")
                self.assertEqual(result.location, "二楼 A-01")
                self.assertEqual(result.status, "available")

    def test_book_id_must_be_a_positive_integer(self):
        self.assertEqual(self.create(book_id=12).book_id, 12)
        for book_id in (0, -1, True, False, 1.5, "1", None):
            with self.subTest(book_id=book_id):
                with self.assertRaises(ValidationError):
                    self.create(book_id=book_id)

    def test_barcode_and_location_are_required_and_nonblank(self):
        for schema in (BookCopyCreateRequest, BookCopyUpdateRequest):
            for field in ("barcode", "location"):
                for value in (None, "", " \t\n "):
                    with self.subTest(schema=schema.__name__, field=field, value=value):
                        values = {"barcode": "LIB-0001", "location": "二楼 A-01"}
                        if schema is BookCopyCreateRequest:
                            values["book_id"] = 1
                        if value is None:
                            del values[field]
                        else:
                            values[field] = value
                        with self.assertRaises(ValidationError):
                            schema(**values)

    def test_only_supported_catalogue_statuses_are_accepted(self):
        for request in (self.create, self.update):
            for status in ("available", "maintenance", "withdrawn"):
                with self.subTest(operation=request.__name__, status=status):
                    self.assertEqual(request(status=status).status, status)
            for status in ("borrowed", "lost", "AVAILABLE", "", None):
                with self.subTest(operation=request.__name__, status=status):
                    with self.assertRaises(ValidationError):
                        request(status=status)

    def test_update_cannot_reassign_a_copy_to_another_book(self):
        for book_id in (1, 2):
            with self.subTest(book_id=book_id):
                with self.assertRaises(ValidationError):
                    self.update(book_id=book_id)

    def test_unknown_copy_input_fields_are_rejected(self):
        for request in (self.create, self.update):
            with self.subTest(operation=request.__name__):
                with self.assertRaises(ValidationError):
                    request(available_copies=3)


class BookResponseTest(unittest.TestCase):
    def book_attributes(self, **changes):
        values = {
            "id": 1,
            "title": "Python 编程入门",
            "author": "测试作者",
            "isbn": "9787115428028",
            "publisher": "测试出版社",
            "publication_year": 2024,
            "category": "编程",
            "description": "面向零基础读者的学习指南。",
            "cover": None,
            "is_active": True,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def copy_attributes(self):
        return SimpleNamespace(
            id=11, book_id=1, barcode="LIB-0001", location="二楼 A-01", status="available"
        )

    def test_book_response_reads_attributes_and_exposes_derived_inventory(self):
        response = BookResponse.model_validate(
            self.book_attributes(total_copies=3, available_copies=2)
        )
        self.assertEqual(response.id, 1)
        self.assertEqual(response.title, "Python 编程入门")
        self.assertEqual(response.isbn, "9787115428028")
        self.assertEqual(response.total_copies, 3)
        self.assertEqual(response.available_copies, 2)
        self.assertNotIn("copies", response.model_dump())

    def test_book_response_defaults_inventory_when_counts_are_not_loaded(self):
        response = BookResponse.model_validate(self.book_attributes())
        self.assertEqual(response.total_copies, 0)
        self.assertEqual(response.available_copies, 0)

    def test_book_response_rejects_negative_inventory(self):
        for field in ("total_copies", "available_copies"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    BookResponse.model_validate(self.book_attributes(**{field: -1}))

    def test_copy_response_reads_attributes(self):
        response = BookCopyResponse.model_validate(self.copy_attributes())
        self.assertEqual(
            response.model_dump(),
            {
                "id": 11,
                "book_id": 1,
                "barcode": "LIB-0001",
                "location": "二楼 A-01",
                "status": "available",
            },
        )

    def test_page_items_default_to_independent_lists(self):
        cases = (
            (BookPageResponse, BookResponse.model_validate(self.book_attributes())),
            (BookCopyPageResponse, BookCopyResponse.model_validate(self.copy_attributes())),
        )
        for schema, item in cases:
            with self.subTest(schema=schema.__name__):
                first = schema(total=0, page=1, page_size=10)
                second = schema(total=0, page=1, page_size=10)
                self.assertEqual(first.items, [])
                self.assertEqual(second.items, [])
                first.items.append(item)
                self.assertEqual(second.items, [])

    def test_page_reads_nested_attribute_objects(self):
        cases = (
            (BookPageResponse, self.book_attributes(), "title", "Python 编程入门"),
            (BookCopyPageResponse, self.copy_attributes(), "barcode", "LIB-0001"),
        )
        for schema, item, field, expected in cases:
            with self.subTest(schema=schema.__name__):
                response = schema(total=1, page=1, page_size=10, items=[item])
                self.assertEqual(len(response.items), 1)
                self.assertEqual(getattr(response.items[0], field), expected)

    def test_page_rejects_invalid_totals_and_pagination(self):
        for schema in (BookPageResponse, BookCopyPageResponse):
            for field, invalid_values in (
                ("total", (-1,)),
                ("page", (0, -1)),
                ("page_size", (0, -1, 101)),
            ):
                for value in invalid_values:
                    with self.subTest(schema=schema.__name__, field=field, value=value):
                        values = {"total": 0, "page": 1, "page_size": 10}
                        values[field] = value
                        with self.assertRaises(ValidationError):
                            schema(**values)


if __name__ == "__main__":
    unittest.main()
