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


# 原来写死在前端 labStore.js 里的那 6 间实验室，落库后作为初始数据。
# 结构：(实验室字段, 设备列表)，设备每项是 (名称, 型号, 总数, 可用数, 状态)
SEED_LABS = [
    (
        dict(
            name="智能感知实验室",
            code="A-301",
            building="信息楼 A区",
            floor="3F",
            capacity=24,
            category="人工智能",
            status="available",
            description="面向机器视觉、深度学习和智能感知实验，配备高性能 GPU 集群。",
        ),
        [
            ("GPU 工作站", "RTX 4090", 6, 5, "normal"),
            ("机器视觉平台", "MV-VS1200", 4, 4, "normal"),
            ("边缘计算盒", "Jetson Orin", 8, 6, "normal"),
        ],
    ),
    (
        dict(
            name="网络安全实验室",
            code="B-408",
            building="信息楼 B区",
            floor="4F",
            capacity=32,
            category="网络安全",
            status="busy",
            description="支持网络攻防、密码学和安全审计等综合实践教学。",
        ),
        [
            ("攻防靶场平台", "CyberRange-200", 2, 2, "normal"),
            ("网络分析仪", "N9020B", 3, 1, "repair"),
            ("服务器集群", "PowerEdge R750", 12, 10, "normal"),
        ],
    ),
    (
        dict(
            name="嵌入式系统实验室",
            code="C-205",
            building="工程训练中心",
            floor="2F",
            capacity=20,
            category="嵌入式",
            status="available",
            description="提供嵌入式开发、物联网与电子系统设计所需的软硬件环境。",
        ),
        [
            ("数字示波器", "Tektronix MDO34", 6, 6, "normal"),
            ("STM32 开发套件", "STM32F407", 20, 18, "normal"),
            ("逻辑分析仪", "Logic Pro 16", 5, 4, "normal"),
        ],
    ),
    (
        dict(
            name="数字媒体实验室",
            code="D-602",
            building="创新中心",
            floor="6F",
            capacity=28,
            category="数字媒体",
            status="available",
            description="适合虚拟现实、数字内容创作、人机交互与三维动画项目。",
        ),
        [
            ("动作捕捉系统", "OptiTrack Prime 41", 2, 2, "normal"),
            ("VR 头显", "Meta Quest 3", 10, 9, "normal"),
            ("图形工作站", "ThinkStation P620", 8, 7, "normal"),
        ],
    ),
    (
        dict(
            name="云计算联合实验室",
            code="A-507",
            building="信息楼 A区",
            floor="5F",
            capacity=36,
            category="云计算",
            status="maintenance",
            description="部署私有云教学平台，满足分布式计算和云原生实践需求。",
        ),
        [
            ("云平台节点", "PowerEdge R760", 8, 6, "normal"),
            ("存储阵列", "NetApp AFF A250", 2, 2, "normal"),
            ("高速交换机", "Nexus 93180YC", 4, 3, "repair"),
        ],
    ),
    (
        dict(
            name="大数据创新实验室",
            code="B-503",
            building="信息楼 B区",
            floor="5F",
            capacity=40,
            category="大数据",
            status="available",
            description="支持数据采集、分布式处理、可视化和数据挖掘课程实践。",
        ),
        [
            ("Hadoop 集群节点", "PowerEdge R750", 10, 9, "normal"),
            ("数据可视化大屏", "Samsung QB75R", 2, 2, "normal"),
            ("高性能服务器", "ProLiant DL380", 6, 5, "normal"),
        ],
    ),
]


def ensure_labs(db) -> None:
    """按房间号补齐实验室及其设备

    以 code（房间号）作为判重的依据：它是唯一索引，也是"这间实验室有没有
    被登记过"最自然的判断标准。已经存在的整条跳过，不覆盖管理员后来改过的内容。
    """
    created = 0

    for lab_data, equipments in SEED_LABS:
        if db.query(Lab).filter(Lab.code == lab_data["code"]).first():
            print(f"[跳过] 实验室已存在：{lab_data['name']}（{lab_data['code']}）")
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
        print(f"[新增] {lab_data['name']}（{lab_data['code']}），含 {len(equipments)} 种设备")

    if not created:
        print("[跳过] 实验室数据已经齐了")


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
