import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests import test_rag_chat as fixtures
from tests.test_rag_chat import CONFIG, PROFILE, FakeEmbeddings, FakeStore
from app.models.books import Book
from app.models.book_sources import BookSource
from app.models.knowledge import KnowledgeChunk
from app.services import book_discovery


class BookDiscoveryTest(unittest.TestCase):
    setUp = fixtures.RagChatTest.setUp
    add_source = fixtures.RagChatTest.add_source

    def add_edition(self, title="分布式研究", text="主题：多智能体", **kwargs):
        document, version, chunk = self.add_source(text, **kwargs)
        book = Book(title=title, author="研究者", category="计算机")
        self.db.add(book)
        self.db.flush()
        self.db.add(BookSource(book_id=book.id, source_id=f"/books/OL{book.id}M",
            source_url=f"https://openlibrary.org/books/OL{book.id}M", fingerprint="a" * 64,
            knowledge_document_id=document.id, metadata_json={"subjects": ["多智能体"]}))
        self.db.commit()
        return book, document, version, chunk

    def discover(self, query, **kwargs):
        config = SimpleNamespace(**{**vars(CONFIG), "RERANK_ENABLED": False})
        with patch.object(book_discovery, "get_embedding_profile", return_value=PROFILE):
            return book_discovery.discover_books(self.db, query, config=config,
                embeddings=kwargs.pop("embeddings", FakeEmbeddings()),
                store=kwargs.pop("store", FakeStore()), **kwargs)

    def test_exact_title_author_isbn_and_empty_exact(self):
        book, *_ = self.add_edition()
        book.isbn = "9787111128069"
        self.db.commit()
        for query in [book.title, book.author, book.isbn]:
            result = self.discover(query, mode="exact")
            self.assertEqual([b["id"] for b in result["books"]], [book.id])
            self.assertTrue(result["books"][0]["match_reasons"])
        self.assertEqual(self.discover("不存在", mode="exact")["books"], [])

    def test_theme_aggregates_chunks_but_preserves_editions_and_no_stock(self):
        first, _, version, _ = self.add_edition()
        second, *_ = self.add_edition()
        self.db.add(KnowledgeChunk(version_id=version.id, chunk_index=1,
            vector_id="extra", text="多智能体系统", section="主题"))
        self.db.commit()
        result = self.discover("找多智能体相关的书", mode="topic")
        self.assertEqual({b["id"] for b in result["books"]}, {first.id, second.id})
        for book in result["books"]:
            self.assertEqual(book["available_copies"], 0)
            self.assertEqual(book["total_copies"], 0)
            self.assertTrue(book["sources"])

    def test_only_linked_published_documents_enter_vector_scope(self):
        book, document, version, chunk = self.add_edition()
        _, _, unrelated = self.add_source("多智能体")
        test = self
        class ScopedStore:
            def query(self, collection, vector, *, limit, version_ids):
                test.assertEqual(version_ids, [version.id])
                return [{"id": unrelated.vector_id, "distance": 0.01},
                        {"id": chunk.vector_id, "distance": 0.2}]
        result = self.discover("多智能体", mode="topic", store=ScopedStore())
        self.assertEqual({s["document_id"] for b in result["books"] for s in b["sources"]}, {document.id})
        document.status = "disabled"
        self.db.commit()
        self.assertEqual(self.discover("多智能体", mode="topic")["books"][0]["sources"], [])
        book.is_active = False
        self.db.commit()
        self.assertEqual(self.discover("多智能体", mode="topic")["books"], [])

    def test_vector_failure_retains_bm25_and_reports_safe_degradation(self):
        book, *_ = self.add_edition(text="元数据：协作协议")
        result = self.discover("协作协议", mode="topic", embeddings=FakeEmbeddings(RuntimeError("secret")))
        self.assertEqual(result["books"][0]["id"], book.id)
        self.assertEqual(result["retrieval"]["status"], "degraded")
        self.assertIn("vector_unavailable", result["retrieval"]["degraded"])
        self.assertNotIn("secret", str(result))

    def test_category_recall_without_knowledge_and_rag_disabled(self):
        self.db.add(Book(title="年代纪事", author="作者", category="历史图书"))
        self.db.commit()
        result = book_discovery.discover_books(self.db, "推荐一些历史书", mode="topic",
            config=SimpleNamespace(RAG_ENABLED=False))
        self.assertEqual(result["books"][0]["title"], "年代纪事")
        self.assertEqual(result["retrieval"]["status"], "degraded")

    def test_expired_deadline_does_not_start_retrieval(self):
        self.add_edition()
        with self.assertRaises(Exception):
            self.discover("多智能体", mode="topic", deadline=time.monotonic() - 1)
