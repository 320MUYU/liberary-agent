from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


MAX_CONVERSATION_CHARS = 20_000


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4_000)

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("消息内容不能为空")
        return value


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    mode: Literal["chat", "knowledge"] = "chat"

    @model_validator(mode="after")
    def validate_conversation(self):
        if self.messages[-1].role != "user":
            raise ValueError("最后一条消息必须由用户发送")

        total_chars = sum(len(message.content) for message in self.messages)
        if total_chars > MAX_CONVERSATION_CHARS:
            raise ValueError("对话内容过长，请新建对话后重试")
        return self


class ChatSource(BaseModel):
    number: int = Field(gt=0)
    chunk_id: int = Field(gt=0)
    document_id: int = Field(gt=0)
    title: str
    version: int = Field(gt=0)
    page: int | None = None
    section: str | None = None
    excerpt: str


class ChatResponse(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str
    sources: list[ChatSource] = Field(default_factory=list)
    retrieval_status: Literal[
        "not_requested", "matched", "no_match", "insufficient_evidence"
    ] = "not_requested"
