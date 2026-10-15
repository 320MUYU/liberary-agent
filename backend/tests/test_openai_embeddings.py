import json
import unittest
from unittest.mock import patch

import httpx
from pydantic import ValidationError

from app.config import Settings, settings
from app.common.exceptions import BusinessException
from app.services.embedding_service import OpenAICompatibleEmbeddings, create_embeddings, get_embedding_profile


class OpenAIEmbeddingsTest(unittest.TestCase):
    def adapter(self, handler, **kwargs):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return OpenAICompatibleEmbeddings(
            api_key="offline-secret", endpoint="https://example.test/v1",
            model="BAAI/bge-m3", dimensions=2, client=client,
            sleep=lambda _: None, **kwargs,
        )

    def test_batch_order_and_openai_payload(self):
        batches = []

        def handler(request):
            self.assertEqual(str(request.url), "https://example.test/v1/embeddings")
            self.assertEqual(request.headers["Authorization"], "Bearer offline-secret")
            payload = json.loads(request.content)
            self.assertEqual(set(payload), {"model", "input", "encoding_format"})
            self.assertEqual(payload["model"], "BAAI/bge-m3")
            self.assertEqual(payload["encoding_format"], "float")
            batches.append(len(payload["input"]))
            return httpx.Response(200, json={"data": [
                {"index": i, "embedding": [float(text), 1.0]}
                for i, text in reversed(list(enumerate(payload["input"])))
            ]})

        adapter = self.adapter(handler, batch_size=32)
        self.assertEqual(adapter.embed_documents([str(i) for i in range(65)]),
                         [[float(i), 1.0] for i in range(65)])
        self.assertEqual(batches, [32, 32, 1])
        self.assertEqual(adapter.embed_query("1"), [1.0, 1.0])
        self.assertEqual(adapter.embed_documents([]), [])

    def test_invalid_response_and_dimensions(self):
        for data in (None, [], [{"index": 0, "embedding": [1]}],
                     [{"index": 1, "embedding": [1, 2]}],
                     [{"index": 0, "embedding": [True, 1]}],
                     [{"index": 0, "embedding": [0, 0]}]):
            with self.subTest(data=data), self.assertRaises(BusinessException) as raised:
                self.adapter(lambda _: httpx.Response(200, json={"data": data})).embed_query("馆规")
            self.assertEqual(raised.exception.code, 502)

    def test_retry_timeout_and_safe_errors(self):
        for status, attempts in ((401, 1), (429, 3), (503, 3), ("timeout", 3)):
            calls = []

            def handler(request):
                calls.append(request)
                if status == "timeout":
                    raise httpx.ReadTimeout("offline-secret", request=request)
                return httpx.Response(status, text="offline-secret")

            with self.subTest(status=status), self.assertRaises(BusinessException) as raised:
                self.adapter(handler, max_retries=2).embed_query("馆规")
            self.assertEqual(len(calls), attempts)
            self.assertNotIn("offline-secret", str(raised.exception))

    def test_factory_and_provider_space(self):
        with patch.multiple(settings, EMBEDDING_PROVIDER="openai-compatible",
                            EMBEDDING_BASE_URL="https://example.test/v1/",
                            EMBEDDING_API_KEY="offline-secret", EMBEDDING_MODEL="BAAI/bge-m3"):
            self.assertIsInstance(create_embeddings(), OpenAICompatibleEmbeddings)
            profile = get_embedding_profile()
            self.assertEqual(profile["endpoint"], "https://example.test/v1/embeddings")
            with patch.object(settings, "EMBEDDING_API_KEY", "different"):
                self.assertEqual(profile, get_embedding_profile())
            with patch.object(settings, "EMBEDDING_PROVIDER", "dashscope"), patch.object(
                settings, "DASHSCOPE_EMBEDDING_URL", profile["endpoint"]
            ):
                self.assertNotEqual(profile["fingerprint"], get_embedding_profile()["fingerprint"])

    def test_dimension_alias_and_invalid_provider_settings(self):
        values = dict(_env_file=None, DATABASE_URL="sqlite://", JWT_SECRET_KEY="test",
                      JWT_EXPIRE_HOURS=24, JWT_ALGORITHM="HS256",
                      EMBEDDING_PROVIDER="openai-compatible", EMBEDDING_MODEL="BAAI/bge-m3")
        self.assertEqual(Settings(**values, EMBEDDING_DIMENSION=1024).EMBEDDING_DIMENSIONS, 1024)
        for extra in ({"EMBEDDING_DIMENSION": 512}, {"EMBEDDING_BATCH_SIZE": 0},
                      {"EMBEDDING_PROVIDER": "unknown"}):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                Settings(**(values | extra))

    def test_missing_openai_key_never_falls_back_to_dashscope_key(self):
        with patch.multiple(settings, EMBEDDING_API_KEY=None, DASHSCOPE_API_KEY="other-provider-key",
                            EMBEDDING_BASE_URL="https://example.test/v1"):
            with self.assertRaises(BusinessException):
                OpenAICompatibleEmbeddings()


if __name__ == "__main__":
    unittest.main()
