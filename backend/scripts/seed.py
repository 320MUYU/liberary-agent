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
from app.models import Equipment, Lab, User  # noqa: E402
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


# 新安装环境使用的 6 个图书馆学习空间。
# 内部仍沿用 Lab / Equipment 模型以兼容现有接口和数据库。
SEED_LABS = [
    (
        dict(
            name="知行研讨室",
            code="A-301",
            building="主馆东区",
            floor="3F",
            capacity=12,
            category="小组研讨室",
            status="available",
            description="适合课程协作、论文研读和小组讨论，支持无线投屏与远程交流。",
        ),
        [
            ("交互显示屏", "ViewBoard 65", 1, 1, "normal"),
            ("移动白板", "WB-120", 2, 2, "normal"),
            ("视频会议设备", "MeetUp", 1, 1, "normal"),
        ],
    ),
    (
        dict(
            name="静思阅览室",
            code="B-408",
            building="主馆西区",
            floor="4F",
            capacity=32,
            category="静音自习室",
            status="available",
            description="面向长时阅读与个人自习，采用静音管理并提供独立照明。",
        ),
        [
            ("护眼阅读灯", "RL-02", 32, 30, "normal"),
            ("桌面电源插座", "PD-20W", 32, 30, "normal"),
            ("静音储物柜", "LK-24", 24, 23, "normal"),
        ],
    ),
    (
        dict(
            name="无碍学习室",
            code="C-205",
            building="主馆南区",
            floor="2F",
            capacity=10,
            category="无障碍空间",
            status="available",
            description="提供无障碍通行、可调节桌椅与辅助阅读设施，支持多样化学习需求。",
        ),
        [
            ("电动升降桌", "LiftDesk A2", 6, 6, "normal"),
            ("辅助阅读器", "ReadAssist 3", 2, 2, "normal"),
            ("大字键盘", "KB-Large", 4, 4, "normal"),
        ],
    ),
    (
        dict(
            name="文澜多媒体室",
            code="D-602",
            building="数字资源馆",
            floor="6F",
            capacity=28,
            category="多媒体空间",
            status="available",
            description="支持影像资料阅览、课程展示和小型分享活动，配备完整影音设施。",
        ),
        [
            ("高清投影仪", "EB-L260F", 1, 1, "normal"),
            ("会议音响", "Stage 360", 1, 1, "normal"),
            ("公共电脑", "ThinkCentre M90", 12, 11, "normal"),
        ],
    ),
    (
        dict(
            name="古籍阅览室",
            code="A-507",
            building="特藏馆",
            floor="5F",
            capacity=16,
            category="经典阅览室",
            status="maintenance",
            description="用于馆藏古籍与特藏资料阅览，需遵守特藏资料使用规范。",
        ),
        [
            ("专用阅览桌", "Archive Desk", 8, 8, "normal"),
            ("恒温恒湿设备", "TH-200", 2, 2, "normal"),
            ("无紫外阅读灯", "UV-Free L1", 16, 14, "repair"),
        ],
    ),
    (
        dict(
            name="博雅交流室",
            code="B-503",
            building="主馆北区",
            floor="5F",
            capacity=36,
            category="学术交流室",
            status="available",
            description="适合读书会、学术沙龙与跨学科交流，可灵活调整桌椅布局。",
        ),
        [
            ("会议显示屏", "Samsung QB75", 2, 2, "normal"),
            ("无线投屏设备", "ClickShare C-10", 2, 2, "normal"),
            ("可移动桌椅", "FlexSeat", 36, 34, "normal"),
        ],
    ),
]


def ensure_labs(db) -> None:
    """按房间号补齐学习空间及其设施

    以 code（房间号）作为判重的依据：它是唯一索引，也是"这间实验室有没有
    被登记过"最自然的判断标准。已经存在的整条跳过，不覆盖管理员后来改过的内容。
    """
    created = 0

    for lab_data, equipments in SEED_LABS:
        if db.query(Lab).filter(Lab.code == lab_data["code"]).first():
            print(f"[跳过] 学习空间已存在：{lab_data['name']}（{lab_data['code']}）")
            continue

        lab = Lab(**lab_data)
        db.add(lab)
        # flush 而不是 commit：先把 INSERT 发给数据库拿到自增的 lab.id，
        # 后面建设备要用它做外键，但此时还没提交，出问题可以一起回滚
        db.flush()

        for name, model, total, available, status in equipments:
            db.add(
                Equipment(
                    lab_id=lab.id,
                    name=name,
                    model=model,
                    total=total,
                    available=available,
                    status=status,
                )
            )

        db.commit()
        created += 1
        print(f"[新增] {lab_data['name']}（{lab_data['code']}），含 {len(equipments)} 种设施")

    if not created:
        print("[跳过] 学习空间数据已经齐了")


def main() -> None:
    # 建表：项目没有引入 Alembic，表结构靠 create_all 兜底。
    # 注意它只会创建"还不存在的表"，不会给已有的表增删字段。
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        ensure_admin(db)
        ensure_labs(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
