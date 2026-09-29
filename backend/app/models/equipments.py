from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Equipment(Base):
    __tablename__ = "equipments"
    __table_args__ = {"comment": "实验室设备"}

    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="设备名称")
    model: Mapped[str | None] = mapped_column(String(50), comment="型号")
    total: Mapped[int] = mapped_column(default=1, nullable=False, comment="总数量")
    available: Mapped[int] = mapped_column(default=1, nullable=False, comment="可用数量")
    status: Mapped[str] = mapped_column(
        String(20),
        default="normal",
        nullable=False,
        comment="状态：normal-正常，repair-维修中，scrapped-已报废",
    )
    # ondelete="CASCADE" 是数据库层面的级联：ORM 的 cascade 只管得住
    # 走 ORM 的删除，直接用 SQL 删实验室时设备会变成孤儿，这里多上一道保险
    lab_id: Mapped[int] = mapped_column(
        ForeignKey("labs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="所属实验室 id",
    )

    lab: Mapped["Lab"] = relationship("Lab", back_populates="equipments")
