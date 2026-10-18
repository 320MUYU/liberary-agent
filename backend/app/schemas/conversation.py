"""Public messages never carry user identity or implicit business confirmation."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class SendMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    text: str = Field(min_length=1, max_length=1000)
    hint: Literal["auto", "chat", "knowledge", "library", "space"] = "auto"

