import hashlib
import json
import math
import time
from collections.abc import Callable
from numbers import Real
from urllib.parse import urlsplit

import httpx
from langchain_core.embeddings import Embeddings
from pydantic import SecretStr

from app.common.exceptions import BusinessException
from app.config import settings


def _endpoint(value: str) -> str:
    endpoint = str(value or "").strip().rstrip("/")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise BusinessException(code=503, message="知识库向量接口尚未正确配置，请联系管理员")
    return endpoint


def get_embedding_profile(config=None) -> dict:
    """Changing an embedding space creates a separate collection, independent of API keys."""
    config = config or settings
    provider = getattr(config, "EMBEDDING_PROVIDER", "dashscope")
    if provider not in {"dashscope", "openai-compatible"}:
        raise BusinessException(code=503, message="不支持的向量服务类型")
    profile = {
        "model": str(getattr(config, "EMBEDDING_MODEL", "text-embedding-v4")).strip(),
        "endpoint": (_endpoint(getattr(config, "EMBEDDING_BASE_URL", "")) + "/embeddings"
                     if provider == "openai-compatible"
                     else _endpoint(getattr(config, "DASHSCOPE_EMBEDDING_URL", ""))),
        "dimensions": getattr(config, "EMBEDDING_DIMENSIONS", 1024),
    }
    if provider == "openai-compatible":
        profile["provider"] = provider
    if (
        not profile["model"]
        or type(profile["dimensions"]) is not int
        or profile["dimensions"] <= 0
    ):
        raise BusinessException(code=503, message="知识库向量模型尚未正确配置，请联系管理员")
    encoded = json.dumps(profile, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return {**profile, "fingerprint": fingerprint, "collection_name": f"library_{fingerprint[:40]}"}


def collection_name(config=None) -> str:
    return get_embedding_profile(config)["collection_name"]


class DashScopeEmbeddings(Embeddings):
    """LangChain embedding adapter for the native DashScope synchronous HTTP API."""

    BATCH_SIZE = 10

    def __init__(
        self,
        *,
        api_key: SecretStr | str | None = None,
        endpoint: str | None = None,
        model: str | None = None,
        dimensions: int | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        configured_key = api_key if api_key is not None else getattr(settings, "DASHSCOPE_API_KEY", None)
        key = configured_key.get_secret_value() if isinstance(configured_key, SecretStr) else configured_key
        if not isinstance(key, str) or not key.strip():
            raise BusinessException(code=503, message="知识库向量服务尚未配置，请联系管理员")
        self._api_key = key.strip()
        self.endpoint = _endpoint(
            endpoint if endpoint is not None else getattr(settings, "DASHSCOPE_EMBEDDING_URL", "")
        )
        self.model = model if model is not None else getattr(settings, "EMBEDDING_MODEL", "text-embedding-v4")
        self.dimensions = dimensions if dimensions is not None else getattr(settings, "EMBEDDING_DIMENSIONS", 1024)
        self.timeout = timeout if timeout is not None else getattr(settings, "EMBEDDING_TIMEOUT_SECONDS", 15.0)
        self.max_retries = max_retries if max_retries is not None else getattr(settings, "EMBEDDING_MAX_RETRIES", 2)
        if (
            not isinstance(self.model, str)
            or not self.model.strip()
            or type(self.dimensions) is not int
            or self.dimensions <= 0
            or not isinstance(self.timeout, Real)
            or not math.isfinite(self.timeout)
            or self.timeout <= 0
            or type(self.max_retries) is not int
            or not 0 <= self.max_retries <= 5
        ):
            raise BusinessException(code=503, message="知识库向量服务配置无效，请联系管理员")
        self._client = client
        self._sleep = sleep or time.sleep

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]

    def _embed(self, texts: list[str], text_type: str) -> list[list[float]]:
        if not isinstance(texts, list) or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise BusinessException(code=422, message="向量化内容不能为空")
        if not texts:
            return []
        if self._client is not None:
            return self._embed_batches(self._client, texts, text_type)
        # Own only clients we create. A supplied client can be reused by the worker.
        with httpx.Client(timeout=self.timeout) as client:
            return self._embed_batches(client, texts, text_type)

    def _embed_batches(self, client: httpx.Client, texts: list[str], text_type: str) -> list[list[float]]:
        result = []
        for offset in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[offset : offset + self.BATCH_SIZE]
            response = self._request(client, batch, text_type)
            result.extend(self._decode(response, len(batch)))
        return result

    def _request(self, client: httpx.Client, texts: list[str], text_type: str) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            try:
                response = client.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=self._payload(texts, text_type),
                    timeout=self.timeout,
                )
            except httpx.TransportError:
                if attempt == self.max_retries:
                    raise BusinessException(code=503, message="知识库向量服务连接失败，请稍后重试") from None
            else:
                if response.is_success:
                    return response
                retryable = response.status_code == 429 or response.status_code >= 500
                if not retryable or attempt == self.max_retries:
                    raise BusinessException(code=503, message="知识库向量服务暂时不可用，请联系管理员") from None
            self._sleep(min(0.25 * 2**attempt, 2.0))
        raise BusinessException(code=503, message="知识库向量服务暂时不可用，请稍后重试")

    def _payload(self, texts: list[str], text_type: str) -> dict:
        return {
            "model": self.model,
            "input": {"texts": texts},
            "parameters": {"text_type": text_type, "dimension": self.dimensions},
        }

    def _entries(self, response: httpx.Response):
        return response.json()["output"]["embeddings"], "text_index"

    def _decode(self, response: httpx.Response, count: int) -> list[list[float]]:
        try:
            entries, index_key = self._entries(response)
            if not isinstance(entries, list) or len(entries) != count:
                raise ValueError
            ordered = [None] * count
            for entry in entries:
                index = entry[index_key]
                vector = entry["embedding"]
                if (
                    type(index) is not int
                    or not 0 <= index < count
                    or ordered[index] is not None
                    or not isinstance(vector, list)
                    or len(vector) != self.dimensions
                    or any(isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) for value in vector)
                    or not any(value != 0 for value in vector)
                ):
                    raise ValueError
                ordered[index] = [float(value) for value in vector]
            if any(vector is None for vector in ordered):
                raise ValueError
            return ordered
        except (ValueError, TypeError, KeyError, OverflowError):
            raise BusinessException(code=502, message="知识库向量服务返回的数据无效，请联系管理员") from None


class OpenAICompatibleEmbeddings(DashScopeEmbeddings):
    """OpenAI embeddings wire format; reuse bounded transport and vector validation."""

    def __init__(self, *, api_key=None, endpoint=None, batch_size=None, **kwargs):
        super().__init__(
            api_key=api_key if api_key is not None else (settings.EMBEDDING_API_KEY or ""),
            endpoint=_endpoint(endpoint if endpoint is not None else settings.EMBEDDING_BASE_URL) + "/embeddings",
            **kwargs,
        )
        self.BATCH_SIZE = batch_size if batch_size is not None else settings.EMBEDDING_BATCH_SIZE
        if type(self.BATCH_SIZE) is not int or not 1 <= self.BATCH_SIZE <= 128:
            raise BusinessException(code=503, message="向量批量大小配置无效")

    def _payload(self, texts: list[str], text_type: str) -> dict:
        # BGE-M3 has a fixed output size; do not send the optional dimensions parameter.
        return {"model": self.model, "input": texts, "encoding_format": "float"}

    def _entries(self, response: httpx.Response):
        return response.json()["data"], "index"


def create_embeddings(**kwargs) -> Embeddings:
    if settings.EMBEDDING_PROVIDER == "openai-compatible":
        return OpenAICompatibleEmbeddings(**kwargs)
    if settings.EMBEDDING_PROVIDER == "dashscope":
        return DashScopeEmbeddings(**kwargs)
    raise BusinessException(code=503, message="不支持的向量服务类型")
