import math
from numbers import Real
from urllib.parse import quote

import httpx

from app.common.exceptions import BusinessException
from app.config import settings


def _valid_vector(vector) -> bool:
    return (
        isinstance(vector, list)
        and bool(vector)
        and all(not isinstance(value, bool) and isinstance(value, Real) and math.isfinite(value) for value in vector)
        and any(value != 0 for value in vector)
    )


class CollectionNotFound(Exception):
    status_code = 404


class NativeChromaHttpClient:
    """Small Chroma v2 HTTP client with a finite timeout, including the first request.

    Chroma 1.5.9's Python HTTP SDK uses an unbounded timeout during construction.
    Native HTTP also avoids embedding model initialization and private SDK hooks.
    Keep the optional real-server smoke test enabled when upgrading the server.
    """

    def __init__(self, *, host="127.0.0.1", port=8001, timeout=10.0, client=None):
        if not isinstance(timeout, Real) or not math.isfinite(timeout) or timeout <= 0:
            raise BusinessException(code=503, message="知识库索引服务超时配置无效")
        self.timeout = float(timeout)
        self.base_url = str(httpx.URL(scheme="http", host=host, port=port)).rstrip("/")
        self.path = "/api/v2/tenants/default_tenant/databases/default_database/collections"
        self._client = client

    def _request(self, method, path, data=None):
        try:
            kwargs = {"timeout": self.timeout}
            if data is not None:
                kwargs["json"] = data
            if self._client is None:
                with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                    response = client.request(method, self.base_url + path, **kwargs)
            else:
                response = self._client.request(method, self.base_url + path, **kwargs)
            if response.status_code == 404:
                raise CollectionNotFound()
            if not response.is_success:
                raise BusinessException(code=503, message="知识库索引服务暂时不可用，请稍后重试")
            return response.json() if response.content else None
        except CollectionNotFound:
            raise
        except BusinessException:
            raise
        except (httpx.TransportError, ValueError, TypeError):
            raise BusinessException(code=503, message="知识库索引服务暂时不可用，请稍后重试") from None

    def get_or_create_collection(self, name, *, embedding_function=None, configuration=None):
        data = self._request("POST", self.path, {
            "name": name,
            "configuration": configuration,
            "get_or_create": True,
        })
        return NativeChromaCollection(self, data)

    def get_collection(self, name, *, embedding_function=None):
        data = self._request("GET", f"{self.path}/{quote(name, safe='')}")
        return NativeChromaCollection(self, data)

    def close(self):
        # A supplied httpx client belongs to its caller. Owned clients are request-scoped.
        pass


class NativeChromaCollection:
    def __init__(self, client, data):
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise BusinessException(code=503, message="知识库索引服务返回的数据无效")
        self.client = client
        self.path = f"{client.path}/{quote(data['id'], safe='')}"
        self.configuration = data.get("configuration_json") or data.get("configuration") or {}
        self.metadata = data.get("metadata") or {}

    def upsert(self, **data):
        return self.client._request("POST", f"{self.path}/upsert", data)

    def query(self, **data):
        return self.client._request("POST", f"{self.path}/query", data)

    def delete(self, **data):
        return self.client._request("POST", f"{self.path}/delete", data)

    def count(self):
        return self.client._request("GET", f"{self.path}/count")


class ChromaVectorStore:
    """HTTP-only vector storage. Source text remains authoritative in MySQL."""

    UPSERT_BATCH_SIZE = 1000

    def __init__(self, client=None, timeout=None):
        self._client = client
        self._timeout = timeout

    def _get_client(self):
        if self._client is None:
            self._client = NativeChromaHttpClient(
                host=getattr(settings, "CHROMA_HOST", "127.0.0.1"),
                port=getattr(settings, "CHROMA_PORT", 8001),
                timeout=self._timeout if self._timeout is not None else getattr(settings, "CHROMA_TIMEOUT_SECONDS", 10.0),
            )
        return self._client

    @staticmethod
    def _is_missing(exc: Exception) -> bool:
        # Chroma's NotFoundError has no HTTP response; test clients may expose status_code instead.
        return exc.__class__.__name__ in {"NotFoundError", "InvalidCollectionException"} or getattr(exc, "status_code", None) == 404

    @staticmethod
    def _check_cosine(collection):
        configuration = getattr(collection, "configuration", None)
        if isinstance(configuration, dict):
            hnsw = configuration.get("hnsw") or {}
            space = hnsw.get("space")
        else:
            space = None
        if space is None:
            space = (getattr(collection, "metadata", None) or {}).get("hnsw:space")
        if space != "cosine":
            raise BusinessException(code=503, message="知识库索引配置不匹配，请重新建立索引")

    def upsert(self, collection: str, ids: list[str], texts: list[str], embeddings: list[list[float]], metadatas: list[dict]):
        if not ids:
            if texts or embeddings or metadatas:
                raise BusinessException(code=422, message="知识库索引数据数量不一致")
            return
        if (
            not len(ids) == len(texts) == len(embeddings) == len(metadatas)
            or any(not isinstance(identifier, str) or not identifier.strip() for identifier in ids)
            or len(set(ids)) != len(ids)
            or any(not isinstance(text, str) or not text.strip() for text in texts)
            or any(not _valid_vector(vector) for vector in embeddings)
            or len({len(vector) for vector in embeddings}) != 1
            or any(not isinstance(metadata, dict) for metadata in metadatas)
        ):
            raise BusinessException(code=422, message="知识库索引数据无效")
        normalized = [
            {**metadata, **({"version_id": str(metadata["version_id"])} if "version_id" in metadata else {})}
            for metadata in metadatas
        ]
        try:
            target = self._get_client().get_or_create_collection(
                name=collection,
                embedding_function=None,
                configuration={"hnsw": {"space": "cosine"}},
            )
            self._check_cosine(target)
            for offset in range(0, len(ids), self.UPSERT_BATCH_SIZE):
                end = offset + self.UPSERT_BATCH_SIZE
                target.upsert(
                    ids=ids[offset:end],
                    documents=texts[offset:end],
                    embeddings=embeddings[offset:end],
                    metadatas=normalized[offset:end],
                )
        except BusinessException:
            raise
        except Exception:
            raise BusinessException(code=503, message="知识库索引服务暂时不可用，请稍后重试") from None

    def query(self, collection: str, embedding: list[float], limit: int = 8) -> list[dict]:
        if not _valid_vector(embedding) or type(limit) is not int or not 1 <= limit <= 100:
            raise BusinessException(code=422, message="知识库检索参数无效")
        try:
            target = self._get_client().get_collection(name=collection, embedding_function=None)
        except Exception as exc:
            if self._is_missing(exc):
                return []
            raise BusinessException(code=503, message="知识库检索服务暂时不可用，请稍后重试") from None
        try:
            self._check_cosine(target)
            raw = target.query(
                query_embeddings=[embedding], n_results=limit, include=["distances", "metadatas"]
            )
            ids = raw["ids"][0]
            distances = raw["distances"][0]
            metadatas = raw["metadatas"][0]
            if not len(ids) == len(distances) == len(metadatas):
                raise ValueError
            results = []
            for identifier, distance, metadata in zip(ids, distances, metadatas):
                if (
                    not isinstance(identifier, str)
                    or isinstance(distance, bool)
                    or not isinstance(distance, Real)
                    or not math.isfinite(distance)
                    or not isinstance(metadata, dict)
                ):
                    raise ValueError
                results.append({"id": identifier, "distance": float(distance), "metadata": metadata})
            return results
        except BusinessException:
            raise
        except Exception:
            raise BusinessException(code=503, message="知识库检索服务暂时不可用，请稍后重试") from None

    def delete_version(self, collection: str, version_id: int | str):
        try:
            target = self._get_client().get_collection(name=collection, embedding_function=None)
        except Exception as exc:
            if self._is_missing(exc):
                return
            raise BusinessException(code=503, message="知识库索引服务暂时不可用，请稍后重试") from None
        try:
            target.delete(where={"version_id": str(version_id)})
        except Exception:
            raise BusinessException(code=503, message="知识库索引清理失败，请稍后重试") from None
