import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.common.exceptions import BusinessException
from app.services.vector_store import ChromaVectorStore, NativeChromaHttpClient
from app.services import vector_store


class CollectionMissing(Exception):
    status_code = 404


class FakeCollection:
    def __init__(self):
        self.upserts = []
        self.deletes = []
        self.queries = []
        self.configuration = {"hnsw": {"space": "cosine"}}
        self.metadata = {"hnsw:space": "cosine"}
        self.result = {
            "ids": [["chunk-1", "chunk-2"]],
            "distances": [[0.1, 0.5]],
            "metadatas": [[{"version_id": "5"}, {"version_id": "5"}]],
        }

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return self.result

    def delete(self, **kwargs):
        self.deletes.append(kwargs)


class FakeClient:
    def __init__(self):
        self.collection = FakeCollection()
        self.creates = []
        self.gets = []
        self.error = None

    def get_or_create_collection(self, name, **kwargs):
        self.creates.append((name, kwargs))
        if self.error:
            raise self.error
        return self.collection

    def get_collection(self, name, **kwargs):
        self.gets.append((name, kwargs))
        if self.error:
            raise self.error
        return self.collection


class VectorStoreTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.store = ChromaVectorStore(client=self.client)

    def test_lazy_http_client_receives_finite_timeout(self):
        config = SimpleNamespace(CHROMA_HOST="127.0.0.1", CHROMA_PORT=8001, CHROMA_TIMEOUT_SECONDS=3.0)
        with patch.object(vector_store, "settings", config):
            store = ChromaVectorStore()
            client = store._get_client()
        self.assertIsInstance(client, NativeChromaHttpClient)
        self.assertEqual(client.timeout, 3.0)
        self.assertEqual(ChromaVectorStore(timeout=0.4)._get_client().timeout, 0.4)

    def test_native_http_is_bounded_from_first_request_and_errors_are_safe(self):
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.extensions["timeout"], {"connect": 0.2, "read": 0.2, "write": 0.2, "pool": 0.2})
            raise httpx.ReadTimeout("secret upstream detail", request=request)

        session = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(session.close)
        client = NativeChromaHttpClient(host="127.0.0.1", port=8001, timeout=0.2, client=session)
        self.assertEqual(requests, [])
        with self.assertRaises(BusinessException) as raised:
            ChromaVectorStore(client=client).query("library-test", [1.0, 0.0])
        self.assertEqual(raised.exception.code, 503)
        self.assertNotIn("upstream", str(raised.exception))
        self.assertEqual(len(requests), 1)

    def test_upsert_explicit_vectors_disable_automatic_embedding_and_use_cosine(self):
        self.store.upsert(
            "library-test", ["chunk-1"], ["预约说明"], [[0.5, 1.0]], [{"version_id": 5}]
        )

        name, kwargs = self.client.creates[0]
        self.assertEqual(name, "library-test")
        self.assertIsNone(kwargs["embedding_function"])
        self.assertEqual(kwargs["configuration"]["hnsw"]["space"], "cosine")
        self.assertEqual(self.client.collection.upserts[0], {
            "ids": ["chunk-1"],
            "documents": ["预约说明"],
            "embeddings": [[0.5, 1.0]],
            "metadatas": [{"version_id": "5"}],
        })

    def test_query_maps_results_without_invoking_text_embedding(self):
        result = self.store.query("library-test", [0.5, 1.0], limit=4)

        self.assertEqual(result, [
            {"id": "chunk-1", "distance": 0.1, "metadata": {"version_id": "5"}},
            {"id": "chunk-2", "distance": 0.5, "metadata": {"version_id": "5"}},
        ])
        self.assertIsNone(self.client.gets[0][1]["embedding_function"])
        self.assertEqual(self.client.collection.queries[0], {
            "query_embeddings": [[0.5, 1.0]],
            "n_results": 4,
            "include": ["distances", "metadatas"],
        })

    def test_large_upserts_are_split_into_server_safe_batches(self):
        count = 1001
        self.store.upsert(
            "library-test",
            [f"chunk-{index}" for index in range(count)],
            ["馆规"] * count,
            [[0.5, 1.0]] * count,
            [{"version_id": 5}] * count,
        )
        self.assertEqual([len(batch["ids"]) for batch in self.client.collection.upserts], [1000, 1])

    def test_missing_collection_is_empty_but_outage_is_not(self):
        self.client.error = CollectionMissing("not found")
        self.assertEqual(self.store.query("missing", [0.5, 1.0]), [])
        self.store.delete_version("missing", 5)

        self.client.error = RuntimeError("secret upstream exception")
        with self.assertRaises(BusinessException) as raised:
            self.store.query("library-test", [0.5, 1.0])
        self.assertEqual(raised.exception.code, 503)
        self.assertNotIn("upstream", str(raised.exception))

    def test_delete_version_uses_metadata_filter_and_is_idempotent(self):
        self.store.delete_version("library-test", 5)
        self.assertEqual(self.client.collection.deletes, [{"where": {"version_id": "5"}}])

    def test_invalid_upserts_fail_before_network(self):
        cases = [
            (["a"], [], [[1.0, 0.0]], [{"version_id": 1}]),
            (["a", "a"], ["a", "b"], [[1.0], [1.0]], [{}, {}]),
            (["a"], ["a"], [[float("nan")]], [{}]),
            (["a"], ["a"], [[0.0, 0.0]], [{}]),
            (["a", "b"], ["a", "b"], [[1.0], [1.0, 2.0]], [{}, {}]),
        ]
        for ids, texts, embeddings, metadatas in cases:
            with self.subTest(ids=ids, embeddings=embeddings), self.assertRaises(BusinessException):
                self.store.upsert("library-test", ids, texts, embeddings, metadatas)
        self.assertEqual(self.client.creates, [])

    def test_l2_collection_and_malformed_results_are_rejected(self):
        self.client.collection.configuration = {"hnsw": {"space": "l2"}}
        self.client.collection.metadata = {"hnsw:space": "l2"}
        with self.assertRaises(BusinessException):
            self.store.query("library-test", [1.0, 0.0])

        self.client.collection.configuration = {"hnsw": {"space": "cosine"}}
        self.client.collection.result["distances"] = [[float("nan")]]
        with self.assertRaises(BusinessException):
            self.store.query("library-test", [1.0, 0.0])


if __name__ == "__main__":
    unittest.main()
