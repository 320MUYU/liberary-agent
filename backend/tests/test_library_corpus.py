import asyncio
import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app.common.exceptions import BusinessException
from app.models.knowledge import KnowledgeDocument, KnowledgeVersion
from app.models.library_corpus import LibraryCorpusSource
from app.services.library_corpus import load_manifest, sync_corpus
from tests import test_knowledge_service as fixtures


class LibraryCorpusTest(unittest.TestCase):
    tearDown = fixtures.KnowledgeServiceTest.tearDown
    work = fixtures.KnowledgeServiceTest.work

    def setUp(self):
        fixtures.KnowledgeServiceTest.setUp(self)
        self.snapshot_root = Path(self.directory.name) / "snapshots"
        self.snapshot_root.mkdir()
        self.manifest_path = Path(self.directory.name) / "sources.json"
        self.sample = {
            "corpus_key": "hust-library",
            "institution": "华中科技大学图书馆",
            "scope": "external_reference",
            "sources": [self.source("borrowing", "借阅说明：此文件仅为导入测试，不是实际馆规。")],
        }
        patcher = patch.object(fixtures.settings, "KNOWLEDGE_MAX_BYTES", 20000)
        patcher.start()
        self.addCleanup(patcher.stop)

    def source(self, key, text):
        body = text.encode("utf-8")
        (self.snapshot_root / f"{key}.md").write_bytes(body)
        return {
            "key": key, "title": f"测试来源 {key}",
            "url": f"https://lib.hust.edu.cn/#/content/{key}",
            "snapshot": f"{key}.md", "sha256": hashlib.sha256(body).hexdigest(),
            "observed_at": "2026-10-18T08:00:00+08:00",
            "published_at": None, "category": "borrowing",
        }

    def manifest(self, sample=None):
        self.manifest_path.write_text(json.dumps(sample or self.sample, ensure_ascii=False), encoding="utf-8")
        return load_manifest(self.manifest_path)

    def sync(self, sample=None, **kwargs):
        return asyncio.run(sync_corpus(self.db, self.manifest(sample), self.snapshot_root, self.user_id, **kwargs))

    def test_preview_checks_files_without_uploading_or_mutating(self):
        with patch("app.services.library_corpus.upload_document", side_effect=AssertionError("unexpected upload")):
            report = self.sync()
        self.assertFalse(report["applied"])
        self.assertEqual(self.db.query(KnowledgeDocument).count(), 0)
        self.assertEqual(self.db.query(LibraryCorpusSource).count(), 0)

    def test_preview_also_works_before_registry_upgrade(self):
        LibraryCorpusSource.__table__.drop(self.engine)
        report = self.sync()
        self.assertFalse(report["applied"])
        from sqlalchemy import inspect
        self.assertFalse(inspect(self.engine).has_table("library_corpus_sources"))

    def test_upgrade_adds_only_registry_and_is_repeatable(self):
        from scripts.upgrade_library_corpus import upgrade
        from sqlalchemy import inspect
        LibraryCorpusSource.__table__.drop(self.engine)
        self.assertEqual(len(upgrade(self.engine)), 1)
        self.assertFalse(inspect(self.engine).has_table("library_corpus_sources"))
        self.assertEqual(len(upgrade(self.engine, apply=True)), 1)
        self.assertEqual(upgrade(self.engine, apply=True), [])

    def test_repeated_import_reuses_anchor_version_and_only_publishes_ready(self):
        first = self.sync(apply=True, publish=True)["records"][0]
        self.assertEqual(first["document_status"], "draft")
        self.assertEqual(first["version_status"], "queued")
        self.assertEqual(self.sync(apply=True)["records"][0]["version_id"], first["version_id"])
        self.work()
        ready = self.sync(apply=True, publish=True)["records"][0]
        self.assertEqual(ready["document_status"], "published")
        self.assertEqual(self.db.query(LibraryCorpusSource).count(), 1)
        self.assertEqual(self.db.query(KnowledgeDocument).count(), 1)
        self.assertEqual(self.db.query(KnowledgeVersion).count(), 1)

    def test_interrupted_upload_retains_anchor_for_retry(self):
        with patch("app.services.library_corpus.upload_document", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                self.sync(apply=True)
        self.assertEqual(self.db.query(LibraryCorpusSource).count(), 1)
        self.sync(apply=True)
        self.assertEqual(self.db.query(KnowledgeDocument).count(), 1)

    def test_new_content_creates_immutable_version_without_replacing_publication(self):
        first = self.sync(apply=True)["records"][0]
        self.work()
        self.sync(apply=True, publish=True)
        changed = copy.deepcopy(self.sample)
        changed["sources"][0] = self.source("borrowing", "变更的合成测试条款，仍不是实际馆规。")
        second = self.sync(changed, apply=True, publish=True)["records"][0]
        self.assertNotEqual(first["version_id"], second["version_id"])
        self.assertEqual(self.db.get(KnowledgeDocument, first["document_id"]).active_version_id, first["version_id"])

    def test_recapture_date_alone_does_not_create_version(self):
        first = self.sync(apply=True)["records"][0]
        changed = copy.deepcopy(self.sample)
        changed["sources"][0]["observed_at"] = "2026-10-19T08:00:00+08:00"
        second = self.sync(changed, apply=True)["records"][0]
        self.assertEqual(first["version_id"], second["version_id"])

    def test_all_files_are_checked_before_first_business_write(self):
        self.sample["sources"].append(self.source("spaces", "合成空间说明"))
        (self.snapshot_root / "spaces.md").write_text("tampered", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.sync(apply=True)
        self.assertEqual(self.db.query(KnowledgeDocument).count(), 0)

    def test_paths_cannot_escape_snapshot_root(self):
        self.sample["sources"][0]["snapshot"] = "../outside.md"
        with self.assertRaises(ValueError):
            self.sync(apply=True)
        self.assertEqual(self.db.query(KnowledgeDocument).count(), 0)

    def test_source_domain_identity_and_unique_keys_are_checked(self):
        for url in ("https://example.com/rules", "http://lib.hust.edu.cn/rules", "https://lib.hust.edu.cn@evil.test/"):
            sample = copy.deepcopy(self.sample)
            sample["sources"][0]["url"] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.manifest(sample)
        self.sample["sources"].append(copy.deepcopy(self.sample["sources"][0]))
        with self.assertRaises(ValueError):
            self.manifest()

    def test_rebinding_existing_key_to_different_url_is_rejected(self):
        self.sync(apply=True)
        self.sample["sources"][0]["url"] = "https://lib.hust.edu.cn/#/different"
        with self.assertRaises(BusinessException):
            self.sync(apply=True)
        self.assertEqual(self.db.query(KnowledgeVersion).count(), 1)

    def test_unauthorized_and_deleted_anchors_are_not_imported(self):
        with self.assertRaises(BusinessException):
            asyncio.run(sync_corpus(self.db, self.manifest(), self.snapshot_root, 999, apply=True))
        first = self.sync(apply=True)["records"][0]
        self.db.get(KnowledgeDocument, first["document_id"]).status = "deleted"
        self.db.commit()
        with self.assertRaises(BusinessException):
            self.sync(apply=True)
        self.assertEqual(self.db.query(KnowledgeDocument).count(), 1)

    def test_imported_version_carries_reference_scope_and_source_identity(self):
        self.sync(apply=True)
        version = self.db.query(KnowledgeVersion).one()
        text = fixtures.settings.KNOWLEDGE_DIR.joinpath(version.storage_name).read_text(encoding="utf-8")
        self.assertIn("外部参考资料", text)
        self.assertIn("不代表本系统办理规则", text)
        self.assertIn(self.sample["sources"][0]["url"], text)
        self.assertIn(self.sample["sources"][0]["sha256"], text)


