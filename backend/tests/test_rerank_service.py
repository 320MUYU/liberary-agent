import unittest
import httpx

from app.common.exceptions import BusinessException
from app.services.rerank_service import SiliconFlowReranker


class RerankerTest(unittest.TestCase):
    def adapter(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return SiliconFlowReranker(api_key="local-test-secret", client=client)

    def test_payload_and_index_mapping(self):
        import json
        def handler(request):
            self.assertEqual(str(request.url), "https://api.siliconflow.cn/v1/rerank")
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "BAAI/bge-reranker-v2-m3")
            self.assertEqual(payload["top_n"], 2)
            self.assertFalse(payload["return_documents"])
            self.assertEqual(request.extensions["timeout"]["read"], 0.5)
            return httpx.Response(200, json={"results": [
                {"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]})
        self.assertEqual(self.adapter(handler).rank("取消预约", ["签到", "取消"], timeout=0.5),
                         [{"index": 1, "score": 0.9}, {"index": 0, "score": 0.1}])

    def test_invalid_response_never_selects_wrong_document(self):
        for entries in ([{"index": 2, "relevance_score": 0.9}],
                        [{"index": True, "relevance_score": 0.9}],
                        [{"index": 0, "relevance_score": "0.9"}],
                        [{"index": 0, "relevance_score": 0.9}] * 2,
                        [], [{"index": 0, "relevance_score": 1.5}]):
            with self.subTest(entries=entries), self.assertRaises(BusinessException):
                self.adapter(lambda request: httpx.Response(200, json={"results": entries})).rank(
                    "问题", ["甲", "乙"], timeout=1)

    def test_timeout_and_http_errors_are_safe_and_not_retried(self):
        for status in (401, 429, 503):
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(status, text="local-test-secret upstream body")
            with self.assertRaises(BusinessException) as raised:
                self.adapter(handler).rank("问题", ["甲"], timeout=1)
            self.assertEqual(len(calls), 1)
            self.assertNotIn("secret", str(raised.exception))
        def timeout(request):
            raise httpx.ReadTimeout("local-test-secret", request=request)
        with self.assertRaises(BusinessException):
            self.adapter(timeout).rank("问题", ["甲"], timeout=0.1)

    def test_empty_candidates_never_call_provider(self):
        self.assertEqual(self.adapter(lambda r: self.fail("network")).rank("问题", [], timeout=1), [])
