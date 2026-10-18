"""Immutable evaluation answers and versioned administrator judgments."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    report_id: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    payload: Mapped[dict] = mapped_column(JSON)
    imported_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class EvaluationCaseReview(Base):
    __tablename__ = "evaluation_case_reviews"
    __table_args__ = (UniqueConstraint("run_id", "case_id"),)
    run_id: Mapped[int] = mapped_column(ForeignKey("evaluation_runs.id"), index=True)
    case_id: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="pending_human")
    answer_correct: Mapped[bool | None]
    citations_support: Mapped[bool | None]
    notes: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(default=0)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewer: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)

