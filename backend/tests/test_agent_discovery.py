import json
from pathlib import Path
import unittest

from tests import test_book_discovery as fixtures
from app.models.book_sources import BookSource
from app.services.book_discovery import refresh_books


class AgentDiscoveryEvaluationTest(unittest.TestCase):
    setUp = fixtures.BookDiscoveryTest.setUp
    add_source = fixtures.BookDiscoveryTest.add_source
    add_edition = fixtures.BookDiscoveryTest.add_edition
    discover = fixtures.BookDiscoveryTest.discover

    def test_fixed_three_category_questions_keep_evidence_bound_to_editions(self):
        cases = json.loads((Path(__file__).parent / "fixtures/book_discovery.json").read_text(encoding="utf-8"))
        expected = []
        for case in cases:
            book, document, _, _ = self.add_edition(title=case["title"], text="主题：" + case["subjects"][0])
            book.category = case["category"]
            source = self.db.query(BookSource).filter_by(book_id=book.id).one()
            source.metadata_json = {"subjects": case["subjects"]}
            self.db.commit()
            expected.append((book.id, document.id))
        for case, (identifier, document_id) in zip(cases, expected):
            with self.subTest(query=case["query"]):
                result = self.discover(case["query"], mode="topic")
                self.assertEqual(result["books"][0]["id"], identifier)
                self.assertTrue(result["books"][0]["sources"])
                self.assertTrue(all(s["document_id"] == document_id and s["book_id"] == identifier
                    for s in result["books"][0]["sources"]))

    def test_refresh_removes_knowledge_only_result_when_its_last_source_is_disabled(self):
        _, document, _, _ = self.add_edition(text="元数据：协作协议")
        result = self.discover("协作协议", mode="topic")
        self.assertTrue(result["books"])
        document.status = "disabled"
        self.db.commit()
        self.assertEqual(refresh_books(self.db, result["books"]), [])
