"""Bounded multi-query retrieval, rank fusion and explicit evidence eligibility."""

from dataclasses import dataclass, field
import math
from numbers import Real
import time

from app.common.exceptions import BusinessException
from app.services.lexical_retrieval import get_index, published_manifest


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
    result.candidates = rows[:getattr(config, "RAG_FUSION_CANDIDATES", 30)]
    result.rows = [{**row, "eligible": True} for row in result.candidates if base_eligible(row, config)]
    result.timings_ms["total"] = round((time.monotonic() - started) * 1000, 2)
    return result
