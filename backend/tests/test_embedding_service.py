import json
import math
import unittest
from types import SimpleNamespace

import httpx
from pydantic import SecretStr

from app.common.exceptions import BusinessException
from app.services.embedding_service import (
    DashScopeEmbeddings,
    collection_name,
    get_embedding_profile,
)


class EmbeddingServiceTest(unittest.TestCase):
    def embedding(self, handler, **kwargs):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return DashScopeEmbeddings(
            api_key=SecretStr("test-key"),
            endpoint="https://dashscope.example/api/v1/services/embeddings/text-embedding/text-embedding",
            model="text-embedding-v4",
            dimensions=2,
            max_retries=2,
            client=client,
            sleep=lambda delay: None,
            **kwargs,
        )

    def test_documents_batch_by_ten_and_restore_response_order(self):
        requests = []

        def handler(request):
            payload = json.loads(request.content)
            requests.append(payload)
            self.assertEqual(request.headers["Authorization"], "Bearer test-key")
            texts = payload["input"]["texts"]
            return httpx.Response(
                200,
                json={
                    "output": {
                        "embeddings": [
                            {"text_index": index, "embedding": [float(text), 1.0]}
                            for index, text in reversed(list(enumerate(texts)))
                        ]
                    }
                },
            )

        vectors = self.embedding(handler).embed_documents([str(i) for i in range(23)])

        self.assertEqual([len(item["input"]["texts"]) for item in requests], [10, 10, 3])
        self.assertEqual(vectors, [[float(i), 1.0] for i in range(23)])
        self.assertEqual(requests[0]["model"], "text-embedding-v4")
        self.assertEqual(requests[0]["parameters"], {"text_type": "document", "dimension": 2})

    def test_query_uses_query_type_and_empty_documents_make_no_request(self):
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(
                200, json={"output": {"embeddings": [{"text_index": 0, "embedding": [0.5, 1.0]}]}}
            )

        adapter = self.embedding(handler)
        self.assertEqual(adapter.embed_documents([]), [])
        self.assertEqual(adapter.embed_query("预约流程"), [0.5, 1.0])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["parameters"]["text_type"], "query")

    def test_rate_limit_server_error_and_timeout_are_retried(self):
        for first in (429, 503, "timeout"):
            with self.subTest(first=first):
                calls = []

                def handler(request):
                    calls.append(request)
                    if len(calls) == 1:
                        if first == "timeout":
                            raise httpx.ReadTimeout("secret upstream detail", request=request)
                        return httpx.Response(first, text="secret upstream detail")
                    return httpx.Response(
                        200,
                        json={"output": {"embeddings": [{"text_index": 0, "embedding": [0.5, 1.0]}]}},
                    )

                self.assertEqual(self.embedding(handler).embed_query("馆规"), [0.5, 1.0])
                self.assertEqual(len(calls), 2)

    def test_retry_budget_is_finite_and_client_errors_are_not_retried(self):
        for status, expected_calls in ((429, 3), (500, 3), (401, 1), (400, 1)):
            with self.subTest(status=status):
                calls = []

                def handler(request):
                    calls.append(request)
                    return httpx.Response(status, text="test-key: secret upstream detail")

                with self.assertRaises(BusinessException) as raised:
                    self.embedding(handler).embed_query("馆规")
                self.assertEqual(raised.exception.code, 503)
                self.assertNotIn("test-key", str(raised.exception))
                self.assertNotIn("upstream", str(raised.exception))
                self.assertEqual(len(calls), expected_calls)

    def test_invalid_response_vectors_and_indices_are_rejected(self):
        examples = [
            [],
            [{"text_index": 1, "embedding": [0.5, 1.0]}],
            [{"text_index": 0, "embedding": [0.5]}],
            [{"text_index": 0, "embedding": [0.5, math.inf]}],
            [{"text_index": 0, "embedding": [0.5, True]}],
            [{"text_index": False, "embedding": [0.5, 1.0]}],
            [{"text_index": 0, "embedding": [0.5, 1.0]}] * 2,
        ]
        for embeddings in examples:
            with self.subTest(embeddings=embeddings):
                def handler(request):
                    # Build bytes directly so even nonfinite upstream JSON is validated by the adapter.
                    return httpx.Response(200, content=json.dumps({"output": {"embeddings": embeddings}}))

                with self.assertRaises(BusinessException) as raised:
                    self.embedding(handler).embed_query("馆规")
                self.assertEqual(raised.exception.code, 502)

    def test_duplicate_response_indices_and_invalid_json_are_rejected(self):
        def duplicate_handler(request):
            return httpx.Response(
                200,
                json={"output": {"embeddings": [{"text_index": 0, "embedding": [0.0, 1.0]}] * 2}},
            )

        with self.assertRaises(BusinessException):
            self.embedding(duplicate_handler).embed_documents(["第一段", "第二段"])

        with self.assertRaises(BusinessException) as raised:
            self.embedding(lambda request: httpx.Response(200, text="invalid JSON test-key")).embed_query("馆规")
        self.assertEqual(raised.exception.code, 502)
        self.assertNotIn("test-key", str(raised.exception))

    def test_blank_input_and_unconfigured_credentials_have_safe_errors(self):
        adapter = self.embedding(lambda request: self.fail("must not call upstream"))
        for texts in ([" "], ["馆规", ""], [None]):
            with self.subTest(texts=texts), self.assertRaises(BusinessException):
                adapter.embed_documents(texts)
        with self.assertRaises(BusinessException) as raised:
            DashScopeEmbeddings(api_key="", endpoint="https://example.test/embeddings")
        self.assertEqual(raised.exception.code, 503)

    def test_profile_depends_on_endpoint_model_dimension_but_not_key(self):
        config = SimpleNamespace(
            DASHSCOPE_EMBEDDING_URL="https://example.test/embeddings/",
            EMBEDDING_MODEL="text-embedding-v4",
            EMBEDDING_DIMENSIONS=1024,
            DASHSCOPE_API_KEY=SecretStr("first"),
        )
        original = get_embedding_profile(config)
        self.assertEqual(original["collection_name"], collection_name(config))
        self.assertEqual(original["endpoint"], "https://example.test/embeddings")
        self.assertLessEqual(len(original["collection_name"]), 63)
        config.DASHSCOPE_API_KEY = SecretStr("second")
        self.assertEqual(get_embedding_profile(config), original)
        for attribute, value in (
            ("EMBEDDING_DIMENSIONS", 512),
            ("EMBEDDING_MODEL", "another-model"),
            ("DASHSCOPE_EMBEDDING_URL", "https://another.example.test/embeddings"),
        ):
            previous = getattr(config, attribute)
            setattr(config, attribute, value)
            self.assertNotEqual(collection_name(config), original["collection_name"])
            setattr(config, attribute, previous)


if __name__ == "__main__":
    unittest.main()
