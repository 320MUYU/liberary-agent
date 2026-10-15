from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'disabled', 'deleted')",
            name="ck_knowledge_document_status",
        ),
        {"comment": "知识库文档及当前发布版本"},
    )

    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    active_version_id: Mapped[int | None] = mapped_column()
    latest_version_id: Mapped[int | None] = mapped_column()
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    versions: Mapped[list["KnowledgeVersion"]] = relationship(
        back_populates="document", order_by="KnowledgeVersion.version_number"
    )


class KnowledgeVersion(Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_knowledge_version"),
        CheckConstraint(
            "status IN ('queued', 'indexing', 'ready', 'failed')",
            name="ck_knowledge_version_status",
        ),
        CheckConstraint("version_number > 0", name="ck_knowledge_version_number"),
        CheckConstraint("size_bytes >= 0", name="ck_knowledge_version_size"),
        CheckConstraint("chunk_count >= 0", name="ck_knowledge_version_chunks"),
        CheckConstraint("chunk_size > 0 AND chunk_overlap >= 0 AND chunk_overlap < chunk_size", name="ck_knowledge_version_split"),
        {"comment": "知识库文档不可变版本和索引配置"},
    )

    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id"), index=True
    )
    version_number: Mapped[int] = mapped_column()
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    storage_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    chunk_count: Mapped[int] = mapped_column(default=0)
    chunk_size: Mapped[int] = mapped_column(default=800)
    chunk_overlap: Mapped[int] = mapped_column(default=100)
    embedding_profile: Mapped[str] = mapped_column(String(255))
    collection_name: Mapped[str] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(Text)

    document: Mapped[KnowledgeDocument] = relationship(back_populates="versions")
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="version", order_by="KnowledgeChunk.chunk_index"
    )
    jobs: Mapped[list["KnowledgeJob"]] = relationship(back_populates="version")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "chunk_index", name="uq_knowledge_chunk_order"),
        CheckConstraint("chunk_index >= 0", name="ck_knowledge_chunk_index"),
        CheckConstraint("page IS NULL OR page > 0", name="ck_knowledge_chunk_page"),
        {"comment": "知识切片正文和来源位置"},
    )

    version_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_versions.id"), index=True
    )
    chunk_index: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column()
    section: Mapped[str | None] = mapped_column(String(500))
    vector_id: Mapped[str] = mapped_column(String(255), unique=True)

    version: Mapped[KnowledgeVersion] = relationship(back_populates="chunks")


class KnowledgeJob(Base):
    __tablename__ = "knowledge_jobs"
    __table_args__ = (
        CheckConstraint("kind IN ('index', 'delete')", name="ck_knowledge_job_kind"),
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name="ck_knowledge_job_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_knowledge_job_attempts"),
        {"comment": "可恢复的知识库索引和清理任务"},
    )

    version_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_versions.id"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), default="index")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)

    version: Mapped[KnowledgeVersion] = relationship(back_populates="jobs")
