import re
from datetime import datetime

from sqlalchemy import DateTime, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings


def create_database_if_not_exists() -> None:
    database_url = make_url(settings.DATABASE_URL)
    database_name = database_url.database

    if database_url.get_backend_name() != "mysql" or not database_name:
        return
    if not re.fullmatch(r"[A-Za-z0-9_]+", database_name):
        raise ValueError(f"不合法的数据库名称: {database_name}")

    server_engine = create_engine(
        database_url.set(database=None),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with server_engine.connect() as connection:
            connection.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
    finally:
        server_engine.dispose()


# 创建会话引擎
engine = create_engine(settings.DATABASE_URL)

# 创建会话工厂
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class Base(DeclarativeBase):
    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="主键ID"
    )
    create_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )
