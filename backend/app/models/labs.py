from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Lab(Base):
    __tablename__ = "labs"
    __table_args__ = {"comment": "实验室"}

    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="实验室名称")
    # code 是房间号（A-301），是学生和老师线下找房间的唯一依据，
    # 所以加唯一索引：从数据库层面拦住"同一间房被登记两次"
    code: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False, comment="房间号，如 A-301"
    )
    building: Mapped[str] = mapped_column(String(50), nullable=False, comment="所属楼栋")
    floor: Mapped[str] = mapped_column(String(10), nullable=False, comment="楼层")
    capacity: Mapped[int] = mapped_column(nullable=False, comment="可容纳人数")
    category: Mapped[str] = mapped_column(String(50), nullable=False, comment="类别")
    status: Mapped[str] = mapped_column(
        String(20),
        default="available",
        nullable=False,
        comment="状态：available-可预约，busy-使用中，maintenance-维护中",
    )
    description: Mapped[str | None] = mapped_column(String(255), comment="简介")
    cover: Mapped[str | None] = mapped_column(
        String(255), comment="封面图 url，存上传接口返回的 /uploads/xxx"
    )

    # cascade="all, delete-orphan"：删实验室时连带删掉它的设备，
    # 不然会留下一堆 lab_id 指向"已经不存在的实验室"的孤儿设备。
    # lazy="selectin"：查实验室列表时顺带把设备一次查出来，
    # 否则 N 间实验室会发 N+1 条 SQL。
    equipments: Mapped[list["Equipment"]] = relationship(
        "Equipment",
        back_populates="lab",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
