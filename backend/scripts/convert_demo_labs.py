"""把项目原有的六条实验室演示数据转换成图书馆学习空间。

脚本不会被应用启动或 seed.py 自动调用。只有确认当前库仍使用官方演示数据时，
才在 backend 目录手动运行：
    .venv/Scripts/python.exe scripts/convert_demo_labs.py

转换按房间号和原名称双重确认，保留 Lab 主键与预约关联。管理员改过名称的记录会跳过。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import Equipment, Lab  # noqa: E402
from scripts.seed import SEED_LABS  # noqa: E402


ORIGINAL_NAMES = {
    "A-301": "智能感知实验室",
    "B-408": "网络安全实验室",
    "C-205": "嵌入式系统实验室",
    "D-602": "数字媒体实验室",
    "A-507": "云计算联合实验室",
    "B-503": "大数据创新实验室",
}


def convert() -> None:
    db = SessionLocal()
    converted = 0
    try:
        for space_data, facilities in SEED_LABS:
            code = space_data["code"]
            space = db.query(Lab).filter(Lab.code == code).first()
            expected_name = ORIGINAL_NAMES[code]
            if not space or space.name != expected_name:
                print(f"[跳过] {code} 不存在或已由管理员修改")
                continue

            for field, value in space_data.items():
                setattr(space, field, value)

            existing = (
                db.query(Equipment)
                .filter(Equipment.lab_id == space.id)
                .order_by(Equipment.id)
                .all()
            )
            if len(existing) == len(facilities):
                for item, values in zip(existing, facilities, strict=True):
                    item.name, item.model, item.total, item.available, item.status = values
            else:
                print(f"[提示] {code} 的设施数量已变化，仅转换空间信息")

            converted += 1

        db.commit()
        print(f"[完成] 已转换 {converted} 个学习空间，原主键与预约关联保持不变")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    convert()
