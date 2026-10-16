"""Bounded multi-query retrieval, rank fusion and explicit evidence eligibility."""

from dataclasses import dataclass, field
import math
import logging
from numbers import Real
import time
from sqlalchemy import select

from app.common.exceptions import BusinessException
from app.services.lexical_retrieval import get_index, published_manifest
from app.models.knowledge import KnowledgeChunk, KnowledgeVersion, KnowledgeDocument
from app.services.rerank_service import SiliconFlowReranker


logger = logging.getLogger(__name__)


def source_rows(db, identifiers, fingerprint):
    if not identifiers:
        return {}
    statement = select(KnowledgeChunk, KnowledgeVersion, KnowledgeDocument).join(
        KnowledgeVersion, KnowledgeChunk.version_id == KnowledgeVersion.id,
    ).join(KnowledgeDocument, KnowledgeVersion.document_id == KnowledgeDocument.id).where(
        KnowledgeChunk.vector_id.in_(identifiers), KnowledgeDocument.status == "published",
        KnowledgeDocument.active_version_id == KnowledgeVersion.id,
        KnowledgeVersion.status == "ready", KnowledgeVersion.embedding_profile == fingerprint,
    ).execution_options(populate_existing=True)
    return {chunk.vector_id: (chunk, version, document) for chunk, version, document in db.execute(statement)}


def expand_neighbors(db, rows, published, fingerprint, *, top_k, neighbors):
    anchors, seen_text = [], set()
    for row in rows:
        if row["id"] not in published:
            continue
        normalized = " ".join(published[row["id"]][0].text.split()).casefold()
        if normalized in seen_text:
            continue
        seen_text.add(normalized)
        anchors.append(row)
        if len(anchors) >= top_k:
            break
    extras = []
    seen_ids = {row["id"] for row in anchors}
    if neighbors:
        for row in anchors:
            chunk = published[row["id"]][0]
            candidates = db.scalars(select(KnowledgeChunk).where(
                KnowledgeChunk.version_id == chunk.version_id,
                KnowledgeChunk.chunk_index.in_([chunk.chunk_index + 1, chunk.chunk_index - 1]),
            ).order_by(KnowledgeChunk.chunk_index.desc())).all()
            added = 0
            for adjacent in candidates:
                normalized = " ".join(adjacent.text.split()).casefold()
                if adjacent.vector_id in seen_ids or normalized in seen_text:
                    continue
                seen_text.add(normalized)
                seen_ids.add(adjacent.vector_id)
                extras.append({"id": adjacent.vector_id, "eligible": True, "channels": ["neighbor"]})
                added += 1
                if added >= neighbors:
                    break
    if extras:
        published.update(source_rows(db, [row["id"] for row in extras], fingerprint))
    return anchors + extras


@dataclass
class RetrievalResult:
    rows: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    rerank_status: str = "disabled"
    timings_ms: dict = field(default_factory=dict)


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise BusinessException(code=503, message="知识库检索超时，请稍后重试")
    return seconds


def reciprocal_rank_fusion(lanes, rank_constant=60):
    ranks, rows = {}, {}
    for channel, matches in lanes:
        seen = set()
        for match in matches:
            identifier = match["id"]
            if identifier in seen:
                continue
            seen.add(identifier)
            rank = len(seen)
            ranks[(channel, identifier)] = min(rank, ranks.get((channel, identifier), rank))
            row = rows.setdefault(identifier, {"id": identifier, "channels": []})
            if channel not in row["channels"]:
                row["channels"].append(channel)
            if "distance" in match:
                row["distance"] = min(match["distance"], row.get("distance", math.inf))
            for key in ("bm25_score", "coverage", "strong_match"):
                if key in match:
                    row[key] = max(match[key], row.get(key, 0))
    for identifier, row in rows.items():
        row["channels"].sort()
        row["rrf_score"] = sum(1 / (rank_constant + ranks[(channel, identifier)])
                               for channel in row["channels"])
    return sorted(rows.values(), key=lambda row: (-row["rrf_score"], row["id"]))


def base_eligible(row, config):
    distance = row.get("distance")
    return (
        isinstance(distance, Real) and not isinstance(distance, bool)
        and math.isfinite(distance) and 0 <= distance <= getattr(config, "RAG_MAX_DISTANCE", 0.6)
    ) or (
        row.get("strong_match", False)
        and row.get("coverage", 0) >= getattr(config, "RAG_LEXICAL_MIN_COVERAGE", 0.35)
    )


def retrieve(db, queries, profile, *, config, embeddings, store, deadline, reranker=None, strategy=None):
    started = time.monotonic()
    mode = strategy or getattr(config, "RAG_RETRIEVAL_MODE", "vector")
    if mode not in {"vector", "hybrid", "hybrid_rerank"}:
        raise BusinessException(code=422, message="不支持的检索方式")
    queries = list(dict.fromkeys(query.strip() for query in queries if query.strip()))[:2]
    manifest = published_manifest(db, profile["fingerprint"])
    versions = [item[0] for item in manifest]
    result = RetrievalResult()
    if not versions or not queries:
        return result
    lanes = []
    for query in queries:
        remaining(deadline)
        # Each HTTP adapter receives a fresh share of the remaining request budget.
        if hasattr(embeddings, "timeout"):
            embeddings.timeout = min(embeddings.timeout, remaining(deadline))
        vector = embeddings.embed_query(query)
        remaining(deadline)
        rows = store.query(profile["collection_name"], vector,
                           limit=getattr(config, "RAG_CANDIDATES", 20), version_ids=versions)
        rows = [row for row in rows if isinstance(row.get("id"), str)
                and isinstance(row.get("distance"), Real) and not isinstance(row["distance"], bool)
                and math.isfinite(row["distance"]) and row["distance"] >= 0]
        lanes.append(("vector", rows))
    result.timings_ms["vector"] = round((time.monotonic() - started) * 1000, 2)
    lexical_started = time.monotonic()
    if mode != "vector":
        index = get_index(db, profile["fingerprint"], manifest)
        for query in queries:
            lanes.append(("bm25", index.search(query, getattr(config, "RAG_LEXICAL_CANDIDATES", 20))))
    remaining(deadline)
    result.timings_ms["lexical"] = round((time.monotonic() - lexical_started) * 1000, 2)
    rows = reciprocal_rank_fusion(lanes, getattr(config, "RAG_RRF_K", 60))
    # Refresh publication state before any candidate text is sent to a reranker.
    db.rollback()
    published = source_rows(db, [row["id"] for row in rows], profile["fingerprint"])
    rows = [row for row in rows if row["id"] in published]
    result.candidates = rows[:getattr(config, "RAG_FUSION_CANDIDATES", 30)]
    result.rows = [{**row, "eligible": True} for row in result.candidates if base_eligible(row, config)]
    rerank_enabled = mode == "hybrid_rerank" or (
        strategy is None and mode == "hybrid" and getattr(config, "RERANK_ENABLED", False))
    if rerank_enabled and result.candidates:
        rerank_started = time.monotonic()
        try:
            adapter = reranker or SiliconFlowReranker()
            documents = ["\n".join([published[row["id"]][2].title,
                                     published[row["id"]][0].section or "",
                                     published[row["id"]][0].text]) for row in result.candidates]
            ranking = adapter.rank(queries[-1], documents, timeout=min(
                getattr(config, "RERANK_TIMEOUT_SECONDS", 8), remaining(deadline) / 3))
            result.rows = []
            for ranked in ranking:
                row = result.candidates[ranked["index"]]
                row["rerank_score"] = ranked["score"]
                if ranked["score"] >= getattr(config, "RERANK_MIN_SCORE", 0.15):
                    result.rows.append({**row, "eligible": True})
            result.rerank_status = "applied"
        except BusinessException:
            result.rerank_status = "fallback"
            logger.warning("RAG rerank unavailable; using filtered rank fusion")
        result.timings_ms["rerank"] = round((time.monotonic() - rerank_started) * 1000, 2)
    remaining(deadline)
    result.timings_ms["total"] = round((time.monotonic() - started) * 1000, 2)
    return result
