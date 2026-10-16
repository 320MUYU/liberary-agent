from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    run_id: Mapped[str] = mapped_column(String(36), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    query: Mapped[str] = mapped_column(String(1000))
    task_type: Mapped[str] = mapped_column(String(20), default="borrow", server_default="borrow")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)


class AgentAction(Base):
    __tablename__ = "agent_actions"

    action_id: Mapped[str] = mapped_column(String(36), unique=True)
    run_id: Mapped[str] = mapped_column(String(36), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    snapshot: Mapped[dict] = mapped_column(JSON)
    action_type: Mapped[str] = mapped_column(String(20), default="borrow", server_default="borrow")
    status: Mapped[str] = mapped_column(String(20), default="prepared")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    loan_id: Mapped[int | None] = mapped_column(ForeignKey("book_loans.id"))
