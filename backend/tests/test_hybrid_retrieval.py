import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_rag_chat as fixtures
from test_rag_chat import CONFIG, PROFILE, FakeEmbeddings, FakeStore
from app.services.lexical_retrieval import LexicalIndex, tokenize
from app.services.rag_retrieval import retrieve, reciprocal_rank_fusion
from app.services import rag_service
from app.schemas.ai import ChatRequest


class LexicalTest(unittest.TestCase):
    def test_chinese_identifiers_and_case_normalization(self):
        self.assertIn("r-204", tokenize("请问 R-204 在哪里？"))
        self.assertEqual(tokenize("A4"), tokenize("a4"))
        self.assertEqual(tokenize("？！！"), [])

    def test_single_document_and_zero_overlap(self):
        index = LexicalIndex([{"id": "a", "title": "研讨室", "section": "", "text": "R-204可以使用两小时"}])
        self.assertEqual(index.search("R-204", 10)[0]["id"], "a")
        self.assertEqual(index.search("停车收费", 10), [])
        self.assertEqual(LexicalIndex([]).search("借阅", 10), [])

    def test_title_recall_and_rank_fusion_uses_rank_not_raw_score(self):
        index = LexicalIndex([
            {"id": "a", "title": "遗失读者证", "text": "请到服务台办理", "section": ""},
            {"id": "b", "title": "开放时间", "text": "周一至周五开放", "section": ""},
        ])
        self.assertEqual(index.search("读者证遗失", 2)[0]["id"], "a")
        rows = reciprocal_rank_fusion([
            ("vector", [{"id": "a", "distance": 0.1}, {"id": "b", "distance": 0.2}]),
            ("bm25", [{"id": "b", "bm25_score": 900}, {"id": "c", "bm25_score": 100}]),
        ])
        self.assertEqual(rows[0]["id"], "b")
        self.assertEqual(rows[0]["channels"], ["bm25", "vector"])

    def test_repeated_rewrites_do_not_multiply_channel_votes(self):
        lane = ("vector", [{"id": "a", "distance": 0.1}])
        self.assertEqual(reciprocal_rank_fusion([lane]), reciprocal_rank_fusion([lane, lane]))


class HybridRetrievalTest(unittest.TestCase):
    setUp = fixtures.RagChatTest.setUp
    add_source = fixtures.RagChatTest.add_source

    def run_search(self, question, store=None):
        config = SimpleNamespace(**{**vars(CONFIG), "RAG_RETRIEVAL_MODE": "hybrid"})
        return retrieve(self.db, [question], PROFILE, config=config,
                        embeddings=FakeEmbeddings(), store=store or FakeStore(), deadline=time.monotonic() + 30)

    def test_keyword_route_recovers_missing_vector_match(self):
        _, _, chunk = self.add_source("R-204研讨室位于二层东侧。")
        result = self.run_search("R-204在哪里？")
        self.assertEqual(result.rows[0]["id"], chunk.vector_id)
        self.assertEqual(result.rows[0]["channels"], ["bm25"])
        self.assertIsNone(result.rows[0].get("distance"))

    def test_cached_keywords_stop_returning_disabled_version(self):
        document, _, chunk = self.add_source("R-204研讨室位于二层东侧。")
        self.assertTrue(self.run_search("R-204").rows)
        document.status = "disabled"
        self.db.commit()
        self.assertEqual(self.run_search("R-204").rows, [])

    def test_unpublished_text_cannot_enter_keyword_index(self):
        self.add_source("R-204研讨室位于二层东侧。", document_status="draft")
        self.assertEqual(self.run_search("R-204").rows, [])

    def test_chat_uses_keyword_evidence_without_fabricated_vector_distance(self):
        _, _, chunk = self.add_source("R-204研讨室位于二层东侧。")
        config = SimpleNamespace(**{**vars(CONFIG), "RAG_RETRIEVAL_MODE": "hybrid"})
        with patch.object(rag_service, "settings", config):
            answer = rag_service.knowledge_chat(
                ChatRequest(mode="knowledge", messages=[{"role": "user", "content": "R-204在哪里？"}]),
                self.db, model=fixtures.FakeModel("在二层东侧。[1]"),
                embeddings=FakeEmbeddings(), vector_store=FakeStore(),
            )
        self.assertEqual(answer.sources[0].chunk_id, chunk.id)

    def test_hybrid_followup_retains_original_query(self):
        self.add_source()
        embeddings = FakeEmbeddings()
        config = SimpleNamespace(**{**vars(CONFIG), "RAG_RETRIEVAL_MODE": "hybrid"})
        with patch.object(rag_service, "settings", config):
            rag_service.knowledge_chat(
                ChatRequest(mode="knowledge", messages=[{"role": "user", "content": "研讨室怎么预约？"},
                    {"role": "assistant", "content": "在页面申请"}, {"role": "user", "content": "那能约多久？"}]),
                self.db, model=fixtures.FakeModel("研讨室预约时长", "每天两小时。[1]"),
                embeddings=embeddings, vector_store=FakeStore(),
            )
        self.assertEqual(embeddings.queries, ["那能约多久？", "研讨室预约时长"])
