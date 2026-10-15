from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.books import Book


class BookCopy(Base):
    """一本具有独立条码、位置与流通状态的实体书。"""

    __tablename__ = "book_copies"
    __table_args__ = (
        CheckConstraint(
            "status IN ('available', 'maintenance', 'withdrawn')",
            name="ck_book_copies_status",
        ),
        {"comment": "图书馆藏副本"},
    )

    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="所属书目",
    )
    barcode: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False, comment="馆藏唯一条码"
    )
    location: Mapped[str] = mapped_column(String(100), nullable=False, comment="馆藏位置")
    status: Mapped[str] = mapped_column(
        String(20),
        default="available",
        server_default="available",
        nullable=False,
        comment="状态：available-可借，maintenance-维护中，withdrawn-退役",
    )

    book: Mapped["Book"] = relationship("Book", back_populates="copies")
