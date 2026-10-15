import unittest

from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models as models
from app.database import Base
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeJob,
    KnowledgeVersion,
)
from app.models.users import User
from app.schemas.knowledge import DocumentResponse, PublishRequest, TitleRequest


class KnowledgeModelsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(
            username="knowledge-admin",
            password="unused-test-password",
            name="测试管理员",
            role="admin",
        )
        self.db.add(self.user)
        self.db.flush()
        self.document = KnowledgeDocument(title="预约说明", uploaded_by=self.user.id)
        self.db.add(self.document)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def version(self, number=1):
        item = KnowledgeVersion(
            document_id=self.document.id,
            version_number=number,
            sha256="a" * 64,
            original_name="预约说明.txt",
            storage_name="private-document.txt",
            size_bytes=128,
            embedding_profile="text-embedding-v4:1024",
            collection_name="library_knowledge_v1",
        )
        self.db.add(item)
        self.db.flush()
        return item

    def test_all_models_are_registered_by_package_import(self):
        for model in (
            KnowledgeDocument,
            KnowledgeVersion,
            KnowledgeChunk,
            KnowledgeJob,
        ):
            self.assertIs(getattr(models, model.__name__), model)
            self.assertIn(model.__tablename__, Base.metadata.tables)

    def test_defaults_relationships_and_safe_response(self):
        version = self.version()
        self.document.latest_version_id = version.id
        job = KnowledgeJob(version_id=version.id)
        chunk = KnowledgeChunk(
            version_id=version.id,
            chunk_index=0,
            text="请提前预约。",
            page=3,
            section="预约流程",
            vector_id="version-1-chunk-0",
        )
        self.db.add_all([job, chunk])
        self.db.commit()

        self.assertEqual(self.document.status, "draft")
        self.assertIsNone(self.document.active_version_id)
        self.assertEqual(version.status, "queued")
        self.assertEqual(version.chunk_count, 0)
        self.assertEqual(job.kind, "index")
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.attempts, 0)
        self.assertIsNotNone(job.next_attempt_at)
        self.assertIsNone(job.lease_token)
        self.assertIsNotNone(version.create_time)
        self.assertIsNotNone(version.update_time)

        response = DocumentResponse.model_validate(self.document)
        self.assertEqual(response.versions[0].id, version.id)
        self.assertEqual(response.versions[0].original_name, "预约说明.txt")
        self.assertNotIn("storage_name", response.model_dump()["versions"][0])
        self.assertNotIn("sha256", response.model_dump()["versions"][0])

    def test_document_version_number_is_unique(self):
        self.version()
        with self.assertRaises(IntegrityError):
            self.version()

    def test_chunks_enforce_version_order_and_unique_vector_id(self):
        version = self.version()
        self.db.add(
            KnowledgeChunk(
                version_id=version.id,
                chunk_index=0,
                text="第一段",
                vector_id="unique-vector-id",
            )
        )
        self.db.commit()

        for chunk_index, vector_id in ((0, "different-id"), (1, "unique-vector-id")):
            with self.subTest(chunk_index=chunk_index, vector_id=vector_id):
                self.db.add(
                    KnowledgeChunk(
                        version_id=version.id,
                        chunk_index=chunk_index,
                        text="重复片段",
                        vector_id=vector_id,
                    )
                )
                with self.assertRaises(IntegrityError):
                    self.db.flush()
                self.db.rollback()

    def test_database_rejects_invalid_states_and_negative_counts(self):
        version = self.version()
        job = KnowledgeJob(version_id=version.id)
        self.db.add(job)
        self.db.commit()
        for item, field, value in (
            (self.document, "status", "unknown"),
            (version, "status", "published"),
            (version, "chunk_count", -1),
            (version, "version_number", 0),
            (job, "kind", "upload"),
            (job, "status", "unknown"),
            (job, "attempts", -1),
        ):
            with self.subTest(field=field, value=value):
                setattr(item, field, value)
                with self.assertRaises(IntegrityError):
                    self.db.flush()
                self.db.rollback()

    def test_foreign_keys_reject_orphan_versions(self):
        version = self.version()
        version.document_id = self.document.id + 100
        with self.assertRaises(IntegrityError):
            self.db.flush()


class KnowledgeSchemasTest(unittest.TestCase):
    def test_title_is_trimmed_and_validated_after_trimming(self):
        self.assertEqual(TitleRequest(title="  馆规  ").title, "馆规")
        self.assertEqual(TitleRequest(title=" " + "规" * 200 + " ").title, "规" * 200)
        for title in ("   ", "规" * 201):
            with self.subTest(title_length=len(title)):
                with self.assertRaises(ValidationError):
                    TitleRequest(title=title)

    def test_publish_requires_positive_version_id(self):
        self.assertEqual(PublishRequest(version_id=1).version_id, 1)
        with self.assertRaises(ValidationError):
            PublishRequest(version_id=0)

    def test_document_versions_do_not_share_mutable_default(self):
        first = DocumentResponse(
            id=1,
            title="馆规",
            status="draft",
            active_version_id=None,
            latest_version_id=None,
        )
        second = first.model_copy(deep=True)
        self.assertIsNot(first.versions, second.versions)


if __name__ == "__main__":
    unittest.main()
