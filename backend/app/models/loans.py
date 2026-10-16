from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Loan(Base):
    """借阅申请及实体副本流转历史；只有确认借出才占用副本。"""

    __tablename__ = "book_loans"
    __table_args__ = (
        UniqueConstraint("reader_id", "open_book_id", name="uq_book_loan_reader_open_book"),
        CheckConstraint(
            "status IN ('pending', 'borrowed', 'return_pending', 'returned', 'rejected', 'cancelled')",
            name="ck_book_loan_status",
        ),
        CheckConstraint(
            "(status IN ('pending', 'borrowed', 'return_pending') "
            "AND open_book_id IS NOT NULL AND open_book_id = book_id) OR "
            "(status IN ('returned', 'rejected', 'cancelled') AND open_book_id IS NULL)",
            name="ck_book_loan_open_book",
        ),
        CheckConstraint(
            "(status IN ('borrowed', 'return_pending') AND copy_id IS NOT NULL "
            "AND active_copy_id IS NOT NULL AND active_copy_id = copy_id) OR "
            "(status = 'returned' AND copy_id IS NOT NULL AND active_copy_id IS NULL) OR "
            "(status IN ('pending', 'rejected', 'cancelled') "
            "AND copy_id IS NULL AND active_copy_id IS NULL)",
            name="ck_book_loan_copy_occupancy",
        ),
        CheckConstraint(
            "(status IN ('borrowed', 'return_pending', 'returned') "
            "AND borrowed_at IS NOT NULL AND due_at IS NOT NULL AND due_at > borrowed_at) OR "
            "(status IN ('pending', 'rejected', 'cancelled') "
            "AND borrowed_at IS NULL AND due_at IS NULL)",
            name="ck_book_loan_borrow_dates",
        ),
        CheckConstraint(
            "(status = 'returned' AND return_requested_at IS NOT NULL AND returned_at IS NOT NULL) OR "
            "(status = 'return_pending' AND return_requested_at IS NOT NULL AND returned_at IS NULL) OR "
            "(status IN ('pending', 'borrowed', 'rejected', 'cancelled') "
            "AND return_requested_at IS NULL AND returned_at IS NULL)",
            name="ck_book_loan_return_dates",
        ),
        {"comment": "实体图书借阅申请与流转记录"},
    )

    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="RESTRICT"), index=True)
    reader_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # copy_id 保留历史；active_copy_id 只在借出/待确认归还时有值，唯一索引防重复借出。
    copy_id: Mapped[int | None] = mapped_column(ForeignKey("book_copies.id", ondelete="RESTRICT"))
    active_copy_id: Mapped[int | None] = mapped_column(
        ForeignKey("book_copies.id", ondelete="RESTRICT"), unique=True
    )
    # 结束后清空，允许同一读者再次借同一本书；NULL 不与既有历史记录冲突。
    open_book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id", ondelete="RESTRICT"))
    borrowed_at: Mapped[datetime | None] = mapped_column(DateTime)
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    return_requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime)
    borrowed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    returned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reject_reason: Mapped[str | None] = mapped_column(String(500))
