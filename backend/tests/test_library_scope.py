import unittest
from unittest.mock import patch

from app.models.library_corpus import LibraryCorpusSource
from app.schemas.ai import ChatRequest
from app.services import rag_service
from tests import test_rag_chat as fixtures


class LibraryScopeTest(unittest.TestCase):
    setUp = fixtures.RagChatTest.setUp
    add_source = fixtures.RagChatTest.add_source
    ask = fixtures.RagChatTest.ask
    request = fixtures.RagChatTest.request

    def reference(self):
        doc, version, chunk = self.add_source("本科生借书册数20册，借期4周。")
        doc.title = "华中科技大学图书馆｜各类读者借书权限"
        self.db.add(LibraryCorpusSource(corpus_key="hust-library", source_key="permissions", document_id=doc.id,
            institution="华中科技大学图书馆", source_url="https://lib.hust.edu.cn/index.html#/rtfDetailsBtnLink?id=1426&pid=1387",
            scope="external_reference", metadata_json={"observed_at": "2026-10-18T08:00:00+08:00"}))
        self.db.commit()
        return doc, version, chunk

    def test_explicit_local_policy_never_uses_external_reference_even_with_history(self):
        self.reference()
        request = ChatRequest(mode="knowledge", messages=[
            {"role": "user", "content": "华科本科生能借20册吗？"},
            {"role": "assistant", "content": "华科公开参考资料记载20册。"},
            {"role": "user", "content": "那么本系统也能借20册吗？"}])
        model = fixtures.FakeModel("本系统可借20册。[1]")
        response = self.ask(fixtures.FakeStore(), model=model, request=request)
        self.assertEqual(response.retrieval_status, "no_match")
        self.assertIn("外部参考", response.content)
        self.assertEqual(response.sources, [])
        self.assertEqual(model.calls, [])

    def test_local_evidence_is_kept_and_external_evidence_is_filtered_before_retrieval(self):
        external, external_version, external_chunk = self.reference()
        local, version, chunk = self.add_source("本系统每人最多同时借阅5册。")
        local.title = "本系统借阅说明"
        self.db.commit()
        owner = self
        class Store:
            def query(self, collection, vector, limit=8, *, version_ids=None):
                owner.assertNotIn(external_version.id, version_ids)
                owner.assertIn(version.id, version_ids)
                return [{"id": chunk.vector_id, "distance": 0.1}]
        request = ChatRequest(mode="knowledge", messages=[{"role": "user", "content": "阅见本系统最多同时借几本？"}])
        response = self.ask(Store(), model=fixtures.FakeModel("本系统最多同时借5册。[1]"), request=request)
        self.assertEqual([source.document_id for source in response.sources], [local.id])

    def test_external_answer_is_labelled_and_model_receives_source_scope(self):
        doc, _, chunk = self.reference()
        model = fixtures.FakeModel("华科本科生可借20册。[1]")
        request = ChatRequest(mode="knowledge", messages=[{"role": "user", "content": "华科本科生最多能借几册？"}])
        response = self.ask(fixtures.FakeStore([{"id": chunk.vector_id, "distance": 0.1}]), model=model, request=request)
        self.assertEqual(response.retrieval_status, "matched")
        self.assertIn("外部参考资料", response.content)
        self.assertIn("不代表本系统办理规则", response.content)
        self.assertIn("external_reference", model.calls[0][1].content)
        self.assertIn("https://lib.hust.edu.cn", model.calls[0][1].content)

    def test_existing_knowledge_still_works_before_registry_upgrade(self):
        LibraryCorpusSource.__table__.drop(self.engine)
        _, _, chunk = self.add_source()
        response = self.ask(fixtures.FakeStore([{"id": chunk.vector_id, "distance": 0.1}]))
        self.assertEqual(response.retrieval_status, "matched")

    def test_planner_cannot_add_local_scope_or_replace_a_negative_user_condition(self):
        doc, _, chunk = self.reference()
        chunk.text = "已被另一读者预约的图书不能续借。"
        self.db.commit()
        original = "华科图书还没过期，但被另一位读者预约了，我还能续借吗？只问规定。"
        request = ChatRequest(mode="knowledge", messages=[{"role": "user",
            "content": "本系统未过期图书是否可以续借？"}])
        model = fixtures.FakeModel("华科已被另一读者预约的图书不能续借。[1]")
        response = rag_service.knowledge_chat(request, self.db, model=model,
            embeddings=fixtures.FakeEmbeddings(),
            vector_store=fixtures.FakeStore([{"id": chunk.vector_id, "distance": 0.1}]),
            original_question=original)
        self.assertEqual(response.retrieval_status, "matched")
        self.assertEqual(response.sources[0].document_id, doc.id)
        self.assertEqual(model.calls[-1][-1].content, original)

    def test_original_local_scope_still_filters_external_sources_when_planner_omits_it(self):
        self.reference()
        model, embeddings = fixtures.FakeModel(), fixtures.FakeEmbeddings()
        request = ChatRequest(mode="knowledge", messages=[{"role": "user", "content": "华科本科生能借20册吗？"}])
        response = rag_service.knowledge_chat(request, self.db, model=model,
            embeddings=embeddings, vector_store=fixtures.FakeStore(),
            original_question="那么阅见本系统也能借20册吗？")
        self.assertEqual(response.retrieval_status, "no_match")
        self.assertEqual(response.sources, [])
        self.assertEqual(embeddings.queries, [])
        self.assertEqual(model.calls, [])


