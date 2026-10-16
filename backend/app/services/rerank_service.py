"""SiliconFlow rerank adapter with strict index mapping and safe bounded failures."""

import math
from numbers import Real

import httpx
from pydantic import SecretStr

from app.common.exceptions import BusinessException
from app.config import settings
from app.services.embedding_service import _endpoint


class SiliconFlowReranker:
    def __init__(self, *, api_key=None, base_url=None, model=None, client=None):
        key = api_key if api_key is not None else settings.RERANK_API_KEY
        self._key = key.get_secret_value() if isinstance(key, SecretStr) else key
        if not isinstance(self._key, str) or not self._key.strip():
            raise BusinessException(code=503, message="知识库重排服务尚未配置")
        self.endpoint = _endpoint(base_url or settings.RERANK_BASE_URL) + "/rerank"
        self.model = model or settings.RERANK_MODEL
        self.client = client

    def rank(self, query: str, documents: list[str], *, timeout: float) -> list[dict]:
        if not documents:
            return []
        if (not query.strip() or len(documents) > 100 or any(not text.strip() for text in documents)
                or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0):
            raise BusinessException(code=422, message="知识库重排参数无效")
        try:
            payload = {"model": self.model, "query": query, "documents": documents,
                       "top_n": len(documents), "return_documents": False}
            kwargs = {"json": payload, "headers": {"Authorization": f"Bearer {self._key.strip()}"},
                      "timeout": timeout}
            if self.client is None:
                with httpx.Client(timeout=timeout, trust_env=False) as client:
                    response = client.post(self.endpoint, **kwargs)
            else:
                response = self.client.post(self.endpoint, **kwargs)
            if not response.is_success:
                raise ValueError("upstream status")
            entries = response.json()["results"]
            if not isinstance(entries, list) or len(entries) != len(documents):
                raise ValueError("incomplete mapping")
            results, seen = [], set()
            for entry in entries:
                index, score = entry["index"], entry["relevance_score"]
                if (type(index) is not int or not 0 <= index < len(documents) or index in seen
                        or isinstance(score, bool) or not isinstance(score, Real)
                        or not math.isfinite(score) or not 0 <= score <= 1):
                    raise ValueError("invalid mapping")
                seen.add(index)
                results.append({"index": index, "score": float(score)})
            return sorted(results, key=lambda row: (-row["score"], row["index"]))
        except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError):
            raise BusinessException(code=503, message="知识库重排服务暂时不可用") from None
