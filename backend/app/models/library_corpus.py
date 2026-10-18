"""Stable source anchors; source snapshots remain immutable knowledge versions."""

from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LibraryCorpusSource(Base):
    __tablename__ = "library_corpus_sources"
    __table_args__ = (
        UniqueConstraint("corpus_key", "source_key", name="uq_library_corpus_source"),
        UniqueConstraint("document_id", name="uq_library_corpus_document"),
        {"comment": "公开馆规来源与知识文档的稳定关联"},
    )

    corpus_key: Mapped[str] = mapped_column(String(80))
    source_key: Mapped[str] = mapped_column(String(80))
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id"))
    institution: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(String(2000))
    scope: Mapped[str] = mapped_column(String(40), default="external_reference")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
