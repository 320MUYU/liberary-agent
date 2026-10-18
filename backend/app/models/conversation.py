"""Durable user-owned conversation and idempotent message processing."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Conversation(Base):
    __tablename__ = "agent_conversations"
    conversation_id: Mapped[str] = mapped_column(String(36), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)


class ConversationTurn(Base):
    __tablename__ = "agent_conversation_turns"
    __table_args__ = (UniqueConstraint("conversation_id", "request_id"),)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("agent_conversations.conversation_id"), index=True)
    request_id: Mapped[str] = mapped_column(String(36))
    request: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    decision: Mapped[dict | None] = mapped_column(JSON)
    reply: Mapped[dict | None] = mapped_column(JSON)
    workflow_id: Mapped[str | None] = mapped_column(String(36), index=True)

