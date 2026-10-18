from app.database import Base
from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import String, text


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"comment": "用户信息"}

    # unique=True + index=True：在数据库层建唯一索引，从根上杜绝重名账号
    # 登录接口靠 username 查人，重名会导致"永远只能登录上第一个"，所以这个约束是必需的
    username: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, comment="账号", nullable=False
    )
    password: Mapped[str] = mapped_column(String(255), comment="密码", nullable=False)
    token_version: Mapped[int] = mapped_column(
        default=0, server_default=text("0"), nullable=False, comment="密码更新时递增，使旧登录凭证失效"
    )
    name: Mapped[str] = mapped_column(String(50), comment="名称", nullable=False)
    role: Mapped[str] = mapped_column(
        String(50), comment="角色: student-学生, admin-管理员", nullable=False
    )

    email: Mapped[str | None] = mapped_column(String(50), comment="邮箱")
    phone: Mapped[str | None] = mapped_column(String(50), comment="手机号")
    avatar: Mapped[str | None] = mapped_column(String(50), comment="头像")
    status:Mapped[int] = mapped_column(default=1,comment="状态：0-禁用，1-正常")
