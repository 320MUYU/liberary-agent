import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_rag_chat as fixtures
from app.services import knowledge_diagnostics
from app.schemas.knowledge import SearchRequest
from app.common.exceptions import BusinessException


class DiagnosticsTest(unittest.TestCase):
    setUp = fixtures.RagChatTest.setUp
    add_source = fixtures.RagChatTest.add_source

    def test_audit_detects_missing_and_extra_ids_even_if_counts_match(self):
        _, version, chunk = self.add_source()
        version.chunk_count = 1
        self.db.commit()
        with patch.object(knowledge_diagnostics, "get_embedding_profile", return_value=fixtures.PROFILE):
            result = knowledge_diagnostics.index_status(self.db, version.id,
                store=SimpleNamespace(version_vector_ids=lambda *args: {"wrong-id"}))
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual((result["missing_count"], result["extra_count"]), (1, 1))
        self.assertNotIn("storage_name", result)

    def test_unknown_version_is_not_audited(self):
        with self.assertRaises(BusinessException) as raised:
            knowledge_diagnostics.index_status(self.db, 999)
        self.assertEqual(raised.exception.code, 404)

    def test_search_exposes_only_current_source_text_and_safe_scores(self):
        _, _, chunk = self.add_source("R-204位于二层东侧。")
        with (patch.object(knowledge_diagnostics, "get_embedding_profile", return_value=fixtures.PROFILE),
              patch.object(knowledge_diagnostics, "settings", fixtures.CONFIG)):
            result = knowledge_diagnostics.search(self.db, SearchRequest(query="R-204", strategy="hybrid"),
                embeddings=fixtures.FakeEmbeddings(), store=fixtures.FakeStore())
        self.assertEqual(result["results"][0]["chunk_id"], chunk.id)
        self.assertEqual(result["results"][0]["channels"], ["bm25"])
        self.assertIsNone(result["results"][0]["distance"])
        self.assertNotIn("storage_name", str(result))
