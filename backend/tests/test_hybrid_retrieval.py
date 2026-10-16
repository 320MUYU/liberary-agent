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
from app.common.exceptions import BusinessException
from app.models.knowledge import KnowledgeChunk


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

    def test_rerank_can_promote_candidate_and_reject_weak_evidence(self):
        _, _, first = self.add_source("研讨室签到规定")
        _, _, second = self.add_source("研讨室提前30分钟取消")
        class Reranker:
            def rank(inner, query, documents, *, timeout):
                self.assertLessEqual(timeout, 8)
                return sorted([{"index": i, "score": 0.9 if "取消" in text else 0.02}
                               for i, text in enumerate(documents)], key=lambda row: -row["score"])
        config = SimpleNamespace(**{**vars(CONFIG), "RERANK_MIN_SCORE": 0.15})
        result = retrieve(self.db, ["取消研讨室"], PROFILE, config=config, embeddings=FakeEmbeddings(),
                          store=FakeStore([{"id": first.vector_id, "distance": 0.1},
                                           {"id": second.vector_id, "distance": 0.8}]),
                          deadline=time.monotonic() + 30, reranker=Reranker(), strategy="hybrid_rerank")
        self.assertEqual(result.rerank_status, "applied")
        self.assertEqual([row["id"] for row in result.rows], [second.vector_id])

    def test_default_rerank_retains_low_scored_relevant_evidence(self):
        _, _, chunk = self.add_source("周一至周五21:30闭馆。")
        ranker = SimpleNamespace(rank=lambda *args, **kwargs: [{"index": 0, "score": 0.07}])
        result = retrieve(self.db, ["工作日几点关门？"], PROFILE, config=CONFIG,
                          embeddings=FakeEmbeddings(), store=FakeStore([{"id": chunk.vector_id, "distance": 0.2}]),
                          deadline=time.monotonic() + 30, reranker=ranker, strategy="hybrid_rerank")
        self.assertEqual([row["id"] for row in result.rows], [chunk.vector_id])

    def test_rerank_failure_keeps_filtered_fusion_and_records_degradation(self):
        _, _, chunk = self.add_source()
        failing = SimpleNamespace(rank=lambda *args, **kwargs: (_ for _ in ()).throw(BusinessException("不可用")))
        result = retrieve(self.db, ["预约"], PROFILE, config=CONFIG, embeddings=FakeEmbeddings(),
                          store=FakeStore([{"id": chunk.vector_id, "distance": 0.1}]),
                          deadline=time.monotonic() + 30, reranker=failing, strategy="hybrid_rerank")
        self.assertEqual(result.rerank_status, "fallback")
        self.assertEqual(result.rows[0]["id"], chunk.vector_id)

    def test_disabled_rerank_never_constructs_model(self):
        self.add_source()
        with patch("app.services.rag_retrieval.SiliconFlowReranker", side_effect=AssertionError("network")):
            self.assertEqual(self.run_search("预约").rerank_status, "disabled")

    def test_duplicate_text_does_not_consume_fusion_slots_but_different_titles_survive(self):
        first_doc, _, first = self.add_source("每人每天只能使用一次。")
        second_doc, _, second = self.add_source(first.text)
        third_doc, _, third = self.add_source(first.text)
        third_doc.title = "打印券使用规定"
        self.db.commit()
        result = self.run_search("使用一次", FakeStore([
            {"id": first.vector_id, "distance": 0.1},
            {"id": second.vector_id, "distance": 0.2},
            {"id": third.vector_id, "distance": 0.3},
        ]))
        self.assertEqual(len(result.candidates), 2)
        self.assertIn(third.vector_id, [row["id"] for row in result.candidates])

    def test_neighbors_preserve_page_and_version_and_exact_duplicates_are_removed(self):
        _, version, chunk = self.add_source("归还图书需要管理员确认。")
        adjacent = KnowledgeChunk(version_id=version.id, chunk_index=1, vector_id="adjacent",
                                  text="确认归还前，仍计入借阅名额。", page=3)
        duplicate = KnowledgeChunk(version_id=version.id, chunk_index=2, vector_id="duplicate",
                                   text=chunk.text, page=4, section=chunk.section)
        self.db.add_all([adjacent, duplicate])
        self.db.commit()
        config = SimpleNamespace(**{**vars(CONFIG), "RAG_NEIGHBOR_CHUNKS": 1, "RAG_TOP_K": 2})
        with patch.object(rag_service, "settings", config):
            answer = rag_service.knowledge_chat(
                ChatRequest(mode="knowledge", messages=[{"role": "user", "content": "归还后还占名额吗"}]),
                self.db, model=fixtures.FakeModel("确认前仍占名额。[1][2]"), embeddings=FakeEmbeddings(),
                vector_store=FakeStore([{"id": chunk.vector_id, "distance": 0.1},
                                       {"id": duplicate.vector_id, "distance": 0.2}]),
            )
        self.assertEqual([s.excerpt for s in answer.sources], [chunk.text, adjacent.text])
        self.assertEqual([s.page for s in answer.sources], [2, 3])
