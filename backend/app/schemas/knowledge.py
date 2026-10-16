from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version_number: int
    original_name: str
    status: Literal["queued", "indexing", "ready", "failed"]
    chunk_count: int
    error_message: str | None = None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: Literal["draft", "published", "disabled", "deleted"]
    active_version_id: int | None = None
    latest_version_id: int | None = None
    versions: list[VersionResponse] = Field(default_factory=list)


class TitleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value):
        return value.strip() if isinstance(value, str) else value


class PublishRequest(BaseModel):
    version_id: int = Field(ge=1)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    strategy: Literal["current", "vector", "hybrid", "hybrid_rerank"] = "current"
    limit: int = Field(default=4, ge=1, le=30)

    @field_validator("query", mode="before")
    @classmethod
    def strip_query(cls, value):
        return value.strip() if isinstance(value, str) else value


class SearchHit(BaseModel):
    chunk_id: int
    document_id: int
    version: int
    title: str
    page: int | None = None
    section: str | None = None
    text: str
    channels: list[Literal["vector", "bm25"]]
    fusion_rank: int
    selected_rank: int | None = None
    distance: float | None = None
    bm25_score: float | None = None
    rrf_score: float
    rerank_score: float | None = None


class SearchResponse(BaseModel):
    strategy: Literal["vector", "hybrid", "hybrid_rerank"]
    rerank_status: Literal["disabled", "applied", "fallback"]
    candidates: list[SearchHit]
    results: list[SearchHit]
    timings_ms: dict[str, float]


class IndexStatusResponse(BaseModel):
    version_id: int
    status: Literal["consistent", "mismatch", "in_progress"]
    store: str
    collection: str
    sql_count: int
    recorded_count: int
    vector_count: int
    missing_count: int
    extra_count: int
    profile_matches_current: bool
