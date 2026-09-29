"""初始化数据脚本

用法（在 backend 目录下执行）：
    .venv/Scripts/python.exe scripts/seed.py

可以重复执行，已经存在的数据会跳过，不会重复插入。
"""

import os
import secrets
import sys
from pathlib import Path

# 直接 python scripts/seed.py 运行时，Python 只把 scripts/ 放进模块搜索路径，
# 找不到 app 包。这里手动把上层目录（backend/）加进去。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.users import User  # noqa: E402
from app.utils.bcrypt import hash_password  # noqa: E402


def ensure_admin(db) -> None:
    """确保库里有一个管理员账号

    为什么必须要这一步：注册接口把 role 写死成 "student"（防止有人自己注册成
    管理员），所以不跑这个脚本的话，数据库里一个 admin 都没有，
    管理后台永远进不去，而且没有任何界面能造出管理员来。

    密码优先读环境变量 SEED_ADMIN_PASSWORD；没设就随机生成一个并打印出来。
    不写死默认密码，是为了避免"admin/admin123"这种账号被顺手留在系统里。
    """
    existing = db.query(User).filter(User.role == "admin").first()
    if existing:
        print(f"[跳过] 已存在管理员账号：{existing.username}")
        return

    username = os.getenv("SEED_ADMIN_USERNAME", "admin")
    password = os.getenv("SEED_ADMIN_PASSWORD") or secrets.token_urlsafe(12)

    # 这个账号名可能已经被注册成普通用户了，撞上唯一索引会直接报错，
    # 所以先查一次，给一句能看懂的提示（和注册接口的查重是同一个道理）
    if db.query(User).filter(User.username == username).first():
        print(f"[失败] 账号 {username} 已被占用，请设置 SEED_ADMIN_USERNAME 换一个")
        return

    admin = User(
        username=username,
        password=hash_password(password),
        name="系统管理员",
        role="admin",
        status=1,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    print("[完成] 已创建管理员账号")
    print(f"       账号：{username}")
    print(f"       密码：{password}")
    if not os.getenv("SEED_ADMIN_PASSWORD"):
        print("       （密码是随机生成的，登录后可以到「个人信息」页面自行修改）")


def main() -> None:
    # 建表：项目没有引入 Alembic，表结构靠 create_all 兜底。
    # 注意它只会创建"还不存在的表"，不会给已有的表增删字段。
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        ensure_admin(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
