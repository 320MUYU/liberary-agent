"""Exercise real auth, API, SQL, parser and worker; only cloud/vector adapters are fake."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models
from app.api.ai import get_chat_db, router as ai_router
from app.api.auth import router as auth_router
from app.api.knowledge import router as knowledge_router
from app.common.exceptions import (
    BusinessException,
    business_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.config import settings
from app.database import Base, get_db
from app.models.users import User
from app.services.knowledge_ingestion import process_next_job
from app.utils.bcrypt import hash_password


class FlowEmbeddings:
    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


class FlowStore:
    def __init__(self):
        self.rows = {}

    def upsert(self, collection, ids, texts, embeddings, metadatas):
        for identifier, metadata in zip(ids, metadatas):
            self.rows[identifier] = {"id": identifier, "distance": 0.1, "metadata": metadata}

    def query(self, collection, embedding, limit=8, *, version_ids=None):
        return [row for row in self.rows.values()
                if version_ids is None or int(row["metadata"]["version_id"]) in version_ids][:limit]

    def delete_version(self, collection, version_id):
        self.rows = {
            key: row for key, row in self.rows.items()
            if row["metadata"]["version_id"] != str(version_id)
        }


class KnowledgeFlowTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        directory = tempfile.TemporaryDirectory(prefix="rag-flow-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.store = FlowStore()
        self.embeddings = FlowEmbeddings()
        profile = {"fingerprint": "offline-flow", "collection_name": "library_flow"}
        patches = [
            patch.object(settings, "RAG_ENABLED", True),
            patch.object(settings, "KNOWLEDGE_DIR", self.directory),
            patch("app.services.knowledge_service.get_embedding_profile", return_value=profile),
            patch("app.services.rag_service.get_embedding_profile", return_value=profile),
            patch("app.services.rag_service.create_embeddings", return_value=self.embeddings),
            patch("app.services.rag_service.ChromaVectorStore", return_value=self.store),
            patch("app.services.ai_services.get_knowledge_model", return_value=SimpleNamespace(
                invoke=lambda messages: SimpleNamespace(text="合成验收资料规定保持安静。[1]")
            )),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        with Session(self.engine) as db:
            password = hash_password("FlowTest123")
            for role in ("admin", "student"):
                db.add(User(username=f"flow_{role}", password=password, name=role, role=role))
            db.commit()

        def session():
            with Session(self.engine) as db:
                yield db

        app = FastAPI()
        for router in (auth_router, knowledge_router, ai_router):
            app.include_router(router, prefix="/api")
        app.add_exception_handler(BusinessException, business_exception_handler)
        app.add_exception_handler(HTTPException, http_exception_handler)
        app.add_exception_handler(RequestValidationError, validation_exception_handler)
        app.dependency_overrides[get_db] = session
        app.dependency_overrides[get_chat_db] = session
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.admin = self.login("admin")
        self.reader = self.login("student")

    def login(self, role):
        response = self.client.post("/api/auth/login", json={
            "username": f"flow_{role}", "password": "FlowTest123"
        })
        self.assertEqual(response.json()["code"], 200)
        return {"Authorization": "Bearer " + response.json()["data"]["token"]}

    def ask(self):
        response = self.client.post("/api/ai/chat", headers=self.reader, json={
            "mode": "knowledge", "messages": [{"role": "user", "content": "合成测试区有什么要求？"}]
        })
        self.assertEqual(response.json()["code"], 200)
        return response.json()["data"]

    def work(self):
        with Session(self.engine) as db:
            return process_next_job(db, embeddings=self.embeddings, store=self.store)

    def test_upload_index_publish_citation_replace_disable_and_delete(self):
        upload = {
            "data": {"title": "合成验收文档"},
            "files": {"file": ("rules.md", "# 合成测试\n合成测试区需要保持安静。".encode(), "text/markdown")},
        }
        self.assertEqual(self.client.post("/api/admin/knowledge/documents", **upload).status_code, 401)
        self.assertEqual(self.client.post("/api/admin/knowledge/documents", headers=self.reader, **upload).status_code, 403)
        response = self.client.post("/api/admin/knowledge/documents", headers=self.admin, **upload)
        self.assertEqual(response.json()["code"], 200)
        document = response.json()["data"]
        document_id = document["id"]
        self.assertEqual(document["versions"][0]["status"], "queued")
        self.assertTrue(self.work())
        self.assertEqual(self.ask()["retrieval_status"], "no_match")

        publish_url = f"/api/admin/knowledge/documents/{document_id}/publish"
        self.assertEqual(self.client.post(publish_url, headers=self.admin).json()["code"], 200)
        answer = self.ask()
        self.assertEqual(answer["retrieval_status"], "matched")
        source = answer["sources"][0]
        self.assertIsInstance(source["chunk_id"], int)
        source_url = f"/api/knowledge/sources/{source['chunk_id']}"
        preview = self.client.get(source_url, headers=self.reader).json()
        self.assertEqual(preview["code"], 200)
        self.assertEqual(preview["data"]["chunk_id"], source["chunk_id"])
        self.assertIn("保持安静", preview["data"]["text"])

        update = self.client.post(
            f"/api/admin/knowledge/documents/{document_id}/versions", headers=self.admin,
            files={"file": ("rules-v2.md", "# 合成测试新版\n合成测试区需要保持安静，关闭手机提示音。".encode())},
        )
        self.assertEqual(update.json()["code"], 200)
        self.assertEqual(self.ask()["sources"][0]["version"], 1)
        self.assertTrue(self.work())
        self.assertEqual(self.client.post(publish_url, headers=self.admin).json()["code"], 200)
        self.assertEqual(self.ask()["sources"][0]["version"], 2)
        self.assertEqual(self.client.get(source_url, headers=self.reader).json()["code"], 404)

        self.client.post(f"/api/admin/knowledge/documents/{document_id}/disable", headers=self.admin)
        self.assertEqual(self.ask()["retrieval_status"], "no_match")
        self.assertEqual(self.client.post(publish_url, headers=self.admin).json()["code"], 200)
        self.assertEqual(self.ask()["retrieval_status"], "matched")
        self.client.delete(f"/api/admin/knowledge/documents/{document_id}", headers=self.admin)
        self.assertEqual(self.ask()["retrieval_status"], "no_match")
        while self.work():
            pass
        self.assertEqual(self.store.rows, {})
        self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
