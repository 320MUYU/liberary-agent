from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = {"comment": "实验室预约"}

    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id"), index=True, nullable=False)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    start: Mapped[str] = mapped_column(String(5), nullable=False)
    end: Mapped[str] = mapped_column(String(5), nullable=False)
    people: Mapped[int] = mapped_column(nullable=False)
    purpose: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True, nullable=False)
    review_note: Mapped[str | None] = mapped_column(String(500))
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)

    lab: Mapped["Lab"] = relationship("Lab")
    applicant: Mapped["User"] = relationship("User", foreign_keys=[applicant_id])
    reviewer: Mapped["User | None"] = relationship("User", foreign_keys=[reviewer_id])
