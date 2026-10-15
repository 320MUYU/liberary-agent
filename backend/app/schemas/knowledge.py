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
