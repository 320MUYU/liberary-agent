import asyncio
import io
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.config import settings
from app.database import Base
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeJob, KnowledgeVersion
from app.models.users import User
from app.services.knowledge_service import (
    delete_document, disable_document, get_source, publish_document, retry_version, upload_document,
)
from app.services.knowledge_ingestion import process_next_job


PROFILE = {"fingerprint": "test-space", "collection_name": "library_test"}


class FakeEmbeddings:
    def embed_documents(self, texts):
        return [[1.0, 0.0] for text in texts]


class FakeStore:
    def __init__(self):
        self.data = {}

    def upsert(self, collection, ids, texts, embeddings, metadatas):
        for identifier, metadata in zip(ids, metadatas):
            self.data[identifier] = metadata

    def delete_version(self, collection, version_id):
        self.data = {key: value for key, value in self.data.items() if value["version_id"] != str(version_id)}

    def version_vector_ids(self, collection, version_id):
        return {key for key, value in self.data.items() if value["version_id"] == str(version_id)}


class KnowledgeServiceTest(unittest.TestCase):
    def test_missing_vector_write_cannot_mark_index_ready(self):
        doc = self.upload()
        self.store.upsert = lambda *args: None
        self.work()
        version = self.db.get(KnowledgeVersion, doc.latest_version_id)
        self.assertEqual(version.status, "failed")
        with self.assertRaises(BusinessException):
            publish_document(self.db, doc.id)

    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        user = User(username="admin-test", password="test", name="测试管理员", role="admin")
        self.db.add(user)
        self.db.commit()
        self.user_id = user.id
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        for name, value in [("KNOWLEDGE_DIR", Path(self.directory.name)), ("RAG_ENABLED", True), ("KNOWLEDGE_MAX_BYTES", 1024)]:
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("app.services.knowledge_service.get_embedding_profile", return_value=PROFILE)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = FakeStore()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def upload(self, text="合成测试规则：学习区禁止大声喧哗。", document_id=None, name="rules.md"):
        return asyncio.run(upload_document(self.db, UploadFile(filename=name, file=io.BytesIO(text.encode())), "测试规则", self.user_id, document_id))

    def work(self):
        return process_next_job(self.db, embeddings=FakeEmbeddings(), store=self.store)

    def test_upload_is_private_queued_and_identical_retry_is_idempotent(self):
        doc = self.upload(name="../../rules.md")
        version = self.db.get(KnowledgeVersion, doc.latest_version_id)
        self.assertEqual(doc.status, "draft")
        self.assertEqual(version.status, "queued")
        self.assertNotIn("..", version.storage_name)
        self.assertEqual(version.original_name, "rules.md")
        self.assertEqual(self.upload(document_id=doc.id).latest_version_id, version.id)
        self.assertEqual(len(list(Path(self.directory.name).iterdir())), 1)
        self.assertEqual(len(self.db.scalars(select(KnowledgeJob)).all()), 1)

    def test_actual_size_and_extension_are_enforced_without_orphans(self):
        for text, filename in [("x" * 1025, "big.txt"), ("x", "old.doc"), ("", "empty.md")]:
            with self.subTest(filename=filename), self.assertRaises(BusinessException):
                self.upload(text, name=filename)
        self.assertEqual(len(list(Path(self.directory.name).iterdir())), 0)
        self.assertEqual(self.db.scalars(select(KnowledgeDocument)).all(), [])

    def test_worker_indexes_but_only_manual_publish_exposes_source(self):
        doc = self.upload()
        with self.assertRaises(BusinessException):
            publish_document(self.db, doc.id)
        self.assertTrue(self.work())
        version = self.db.get(KnowledgeVersion, doc.latest_version_id)
        self.assertEqual(version.status, "ready")
        chunk = self.db.scalar(select(KnowledgeChunk))
        with self.assertRaises(BusinessException):
            get_source(self.db, chunk.id)
        publish_document(self.db, doc.id)
        self.assertIn("禁止", get_source(self.db, chunk.id)["text"])
        disable_document(self.db, doc.id)
        with self.assertRaises(BusinessException):
            get_source(self.db, chunk.id)
        self.assertFalse(self.work())

    def test_failed_update_keeps_old_published_version_and_safe_retry(self):
        doc = self.upload()
        self.work()
        publish_document(self.db, doc.id)
        old_id = doc.active_version_id
        self.upload("新的测试规则", doc.id)
        bad = FakeEmbeddings()
        bad.embed_documents = lambda texts: (_ for _ in ()).throw(RuntimeError("secret-key:/private/path"))
        self.assertTrue(process_next_job(self.db, embeddings=bad, store=self.store))
        version = self.db.get(KnowledgeVersion, doc.latest_version_id)
        self.assertEqual(version.status, "failed")
        self.assertNotIn("secret-key", version.error_message)
        self.assertEqual(doc.active_version_id, old_id)
        retry_version(self.db, version.id)
        self.work()
        publish_document(self.db, doc.id)
        self.assertEqual(doc.active_version_id, version.id)

    def test_cannot_publish_another_documents_version_or_stale_version(self):
        one = self.upload()
        self.work()
        old_id = one.latest_version_id
        two = self.upload("另外一份合成测试规则")
        self.work()
        for identifier in [two.latest_version_id, old_id]:
            if identifier == old_id:
                self.upload("第一份的新版合成测试规则", one.id)
            with self.assertRaises(BusinessException):
                publish_document(self.db, one.id, identifier)

    def test_delete_is_sql_first_and_cleanup_is_retryable(self):
        doc = self.upload()
        self.work()
        publish_document(self.db, doc.id)
        chunk = self.db.scalar(select(KnowledgeChunk))
        delete_document(self.db, doc.id)
        with self.assertRaises(BusinessException):
            get_source(self.db, chunk.id)
        self.work()
        self.assertEqual(self.store.data, {})
        self.assertEqual(len(list(Path(self.directory.name).iterdir())), 0)
        with self.assertRaises(BusinessException):
            publish_document(self.db, doc.id)

    def test_expired_lease_is_recovered_and_job_is_idempotent(self):
        doc = self.upload()
        job = self.db.scalar(select(KnowledgeJob))
        job.status = "running"
        job.lease_token = "crashed-worker"
        job.lease_expires_at = datetime.now() - timedelta(seconds=1)
        job.attempts = 1
        self.db.commit()
        self.work()
        self.assertEqual(job.status, "done")
        self.assertEqual(job.attempts, 2)
        self.assertFalse(self.work())
        self.assertEqual(self.db.get(KnowledgeVersion, doc.latest_version_id).chunk_count, len(self.store.data))

    def test_deleted_before_worker_never_becomes_publishable(self):
        doc = self.upload()
        delete_document(self.db, doc.id)
        while self.work():
            pass
        self.assertEqual(doc.status, "deleted")
        self.assertEqual(self.store.data, {})

    def test_retry_uses_immutable_version_split_settings(self):
        doc = self.upload()
        version = self.db.get(KnowledgeVersion, doc.latest_version_id)
        self.assertEqual(version.chunk_size, 800)
        with patch.object(settings, "RAG_CHUNK_SIZE", 1200), patch("app.services.knowledge_ingestion.parse_document", wraps=__import__("app.services.knowledge_parser", fromlist=["parse_document"]).parse_document) as parser:
            self.work()
            self.assertEqual(parser.call_args.kwargs["chunk_size"], 800)

    def test_recovered_deleted_index_task_removes_late_vectors(self):
        doc = self.upload()
        version = self.db.get(KnowledgeVersion, doc.latest_version_id)
        self.store.data["late"] = {"version_id": str(version.id)}
        delete_document(self.db, doc.id)
        self.work()  # Index job must clean even before the delete job runs.
        self.assertEqual(self.store.data, {})


if __name__ == "__main__":
    unittest.main()
