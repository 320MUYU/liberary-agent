from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BookSource(Base):
    """One reviewed external edition per book; never represents physical stock."""

    __tablename__ = "book_sources"

    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), unique=True, nullable=False)
    source_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    source_url: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    knowledge_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_documents.id"), unique=True
    )
