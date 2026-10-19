"""Durable reader messages; each business event is delivered once per account."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Notification(Base):
    __tablename__ = "reader_notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "event_key", name="uq_reader_notification_event"),
        Index("ix_reader_notification_user_read_id", "user_id", "read_at", "id"),
        CheckConstraint("resource_type IN ('loan', 'reservation')", name="ck_notification_resource_type"),
        CheckConstraint("resource_id > 0", name="ck_notification_resource_id"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    event_key: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text)
    resource_type: Mapped[str] = mapped_column(String(20))
    resource_id: Mapped[int]
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
