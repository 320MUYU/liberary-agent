"""Read-only administrator retrieval comparisons and per-version index audits."""

import time
from sqlalchemy import select

from app.common.exceptions import BusinessException
from app.config import settings
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeVersion
from app.services.embedding_service import create_embeddings, get_embedding_profile
from app.services.rag_retrieval import retrieve, source_rows
from app.services.vector_store import ChromaVectorStore


def search(db, request, *, embeddings=None, store=None, reranker=None):
    if not settings.RAG_ENABLED:
        raise BusinessException(code=503, message="知识库检索尚未启用")
    deadline = time.monotonic() + min(getattr(settings, "RAG_REQUEST_TIMEOUT_SECONDS", 60), 60)
    try:
        profile = get_embedding_profile()
        strategy = None if request.strategy == "current" else request.strategy
        result = retrieve(db, [request.query], profile, config=settings,
            embeddings=embeddings if embeddings is not None else create_embeddings(
                timeout=min(getattr(settings, "EMBEDDING_TIMEOUT_SECONDS", 15), 20), max_retries=0),
            store=store if store is not None else ChromaVectorStore(timeout=5),
            deadline=deadline, reranker=reranker, strategy=strategy)
        db.rollback()
        sources = source_rows(db, [row["id"] for row in result.candidates], profile["fingerprint"])
        selected = [row for row in result.rows if row["id"] in sources][:request.limit]
        selected_rank = {row["id"]: rank for rank, row in enumerate(selected, 1)}
        hits = []
        for rank, row in enumerate(result.candidates, 1):
            if row["id"] not in sources:
                continue
            chunk, version, document = sources[row["id"]]
            hits.append({"chunk_id": chunk.id, "document_id": document.id, "version": version.version_number,
                         "title": document.title, "page": chunk.page, "section": chunk.section, "text": chunk.text,
                         "channels": row["channels"], "fusion_rank": rank,
                         "selected_rank": selected_rank.get(row["id"]),
                         **{key: row.get(key) for key in ("distance", "bm25_score", "rrf_score", "rerank_score")}})
        mode = strategy or getattr(settings, "RAG_RETRIEVAL_MODE", "vector")
        if strategy is None and mode == "hybrid" and getattr(settings, "RERANK_ENABLED", False):
            mode = "hybrid_rerank"
        return {"strategy": mode, "rerank_status": result.rerank_status, "candidates": hits,
                "results": sorted([hit for hit in hits if hit["selected_rank"]], key=lambda hit: hit["selected_rank"]),
                "timings_ms": result.timings_ms}
    except BusinessException:
        raise
    except Exception:
        raise BusinessException(code=503, message="知识库检索检查暂时不可用，请稍后重试") from None


def index_status(db, version_id, *, store=None):
    row = db.execute(select(KnowledgeVersion, KnowledgeDocument).join(
        KnowledgeDocument, KnowledgeVersion.document_id == KnowledgeDocument.id,
    ).where(KnowledgeVersion.id == version_id, KnowledgeDocument.status != "deleted")).first()
    if row is None:
        raise BusinessException(code=404, message="知识文档版本不存在")
    version, document = row
    expected = set(db.scalars(select(KnowledgeChunk.vector_id).where(KnowledgeChunk.version_id == version_id)))
    actual = (store or ChromaVectorStore(timeout=5)).version_vector_ids(version.collection_name, version_id)
    consistent = expected == actual and len(expected) == version.chunk_count and version.status == "ready"
    return {"version_id": version_id,
            "status": "in_progress" if version.status in {"queued", "indexing"} else "consistent" if consistent else "mismatch",
            "store": "Chroma", "collection": version.collection_name,
            "sql_count": len(expected), "recorded_count": version.chunk_count, "vector_count": len(actual),
            "missing_count": len(expected - actual), "extra_count": len(actual - expected),
            "profile_matches_current": version.embedding_profile == get_embedding_profile()["fingerprint"]}
