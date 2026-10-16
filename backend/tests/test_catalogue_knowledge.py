import asyncio
from unittest.mock import patch
import unittest

from app.common.exceptions import BusinessException
from app.config import settings
from app.models.books import Book
from app.models.book_sources import BookSource
from app.models.knowledge import KnowledgeDocument, KnowledgeVersion
from app.services.catalogue_import import import_records
from app.services.catalogue_knowledge import sync_book
from tests import test_knowledge_service as fixtures
from tests.test_catalogue_import import record


class CatalogueKnowledgeTest(unittest.TestCase):
    setUp = fixtures.KnowledgeServiceTest.setUp
    tearDown = fixtures.KnowledgeServiceTest.tearDown
    work = fixtures.KnowledgeServiceTest.work

    def prepare(self):
        patcher = patch.object(settings, "KNOWLEDGE_MAX_BYTES", 10000)
        patcher.start()
        self.addCleanup(patcher.stop)
        return import_records(self.db, [record()])[0]["book_id"]

    def sync(self, book_id, **kwargs):
        return asyncio.run(sync_book(self.db, book_id, self.user_id, **kwargs))

    def test_replay_and_publish_only_after_index_ready(self):
        book_id = self.prepare()
        queued = self.sync(book_id, publish=True)
        self.assertEqual(queued["version_status"], "queued")
        self.assertEqual(queued["document_status"], "draft")
        self.assertEqual(self.sync(book_id)["document_id"], queued["document_id"])
        self.assertEqual(self.db.query(KnowledgeDocument).count(), 1)
        self.assertEqual(self.db.query(KnowledgeVersion).count(), 1)
        self.work()
        result = self.sync(book_id, publish=True)
        self.assertEqual(result["document_status"], "published")
        self.assertEqual(result["version_id"], queued["version_id"])

    def test_failed_upload_keeps_reusable_anchor_without_duplicate_documents(self):
        book_id = self.prepare()
        with patch("app.services.catalogue_knowledge.upload_document", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                self.sync(book_id)
        self.assertEqual(self.db.query(KnowledgeDocument).count(), 1)
        self.sync(book_id)
        self.assertEqual(self.db.query(KnowledgeDocument).count(), 1)
        self.assertEqual(self.db.query(KnowledgeVersion).count(), 1)

    def test_changed_metadata_creates_version_and_inactive_book_disables_evidence(self):
        book_id = self.prepare()
        first = self.sync(book_id)
        self.work()
        self.sync(book_id, publish=True)
        book = self.db.get(Book, book_id)
        book.description = "管理员已核实的主题补充"
        self.db.commit()
        changed = self.sync(book_id, publish=True)
        self.assertNotEqual(changed["version_id"], first["version_id"])
        doc = self.db.get(KnowledgeDocument, first["document_id"])
        self.assertEqual(doc.active_version_id, first["version_id"])
        book.is_active = False
        self.db.commit()
        self.assertEqual(self.sync(book_id, publish=True)["document_status"], "disabled")

    def test_index_failure_retries_same_version_only_when_requested(self):
        book_id = self.prepare()
        first = self.sync(book_id)
        version = self.db.get(KnowledgeVersion, first["version_id"])
        version.status = "failed"
        self.db.commit()
        self.assertEqual(self.sync(book_id)["version_status"], "failed")
        result = self.sync(book_id, retry_failed=True)
        self.assertEqual(result["version_status"], "queued")
        self.assertEqual(result["version_id"], first["version_id"])

    def test_unknown_user_cannot_sync_and_deleted_document_is_not_recreated(self):
        book_id = self.prepare()
        with self.assertRaises(BusinessException):
            asyncio.run(sync_book(self.db, book_id, 999))
        first = self.sync(book_id)
        doc = self.db.get(KnowledgeDocument, first["document_id"])
        doc.status = "deleted"
        self.db.commit()
        with self.assertRaises(BusinessException):
            self.sync(book_id, publish=True)
        self.assertEqual(self.db.query(KnowledgeDocument).count(), 1)
