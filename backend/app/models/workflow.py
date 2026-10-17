from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WorkflowRun(Base):
    __tablename__ = "agent_workflows"
    workflow_id: Mapped[str] = mapped_column(String(36), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    query: Mapped[str] = mapped_column(String(1000))
    request: Mapped[dict] = mapped_column(JSON)
    conditions: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="planning")
    message: Mapped[str | None] = mapped_column(String(500))
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    active_seconds: Mapped[float] = mapped_column(Float, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)


class WorkflowStep(Base):
    __tablename__ = "agent_workflow_steps"
    __table_args__ = (UniqueConstraint("workflow_id", "position"),)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("agent_workflows.workflow_id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    # Reserved before the child exists, so this is intentionally not a foreign key.
    child_run_id: Mapped[str] = mapped_column(String(36), unique=True)
    spec: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    result: Mapped[dict | None] = mapped_column(JSON)
