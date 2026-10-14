from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.book_copies import BookCopy


class Book(Base):
    """书目元数据；库存由对应馆藏副本统计，不单独保存数量。"""

    __tablename__ = "books"
    __table_args__ = (
        CheckConstraint(
            "publication_year IS NULL OR publication_year BETWEEN 1 AND 9999",
            name="ck_books_publication_year",
        ),
        {"comment": "图书书目"},
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="书名")
    author: Mapped[str] = mapped_column(String(255), nullable=False, comment="作者")
    isbn: Mapped[str | None] = mapped_column(
        String(13), unique=True, index=True, comment="规范化的 ISBN，无 ISBN 时为 NULL"
    )
    publisher: Mapped[str | None] = mapped_column(String(255), comment="出版社")
    publication_year: Mapped[int | None] = mapped_column(comment="出版年份")
    category: Mapped[str] = mapped_column(
        String(100), default="未分类", nullable=False, index=True, comment="图书分类"
    )
    description: Mapped[str | None] = mapped_column(Text, comment="图书简介")
    cover: Mapped[str | None] = mapped_column(String(255), comment="封面地址")
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False, comment="是否上架"
    )

    # 删除书目不得级联删除实体副本，已有副本的书目应通过下架保留历史。
    copies: Mapped[list["BookCopy"]] = relationship(
        "BookCopy", back_populates="book", lazy="selectin", passive_deletes="all"
    )
