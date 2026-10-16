"""Import a reviewed JSON array of public edition metadata; default is preview only."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--apply", action="store_true", help="写入书目；默认只预览")
    parser.add_argument("--sync-knowledge", action="store_true", help="复用文档索引流程，必须同时 --apply")
    parser.add_argument("--publish", action="store_true", help="发布已就绪的版本，未就绪版本仍保持原状态")
    parser.add_argument("--retry-failed", action="store_true", help="重试失败版本，不创建重复文档")
    parser.add_argument("--admin", default="admin", help="知识库操作对应的本地管理员账号")
    args = parser.parse_args()
    if (args.publish or args.retry_failed) and not args.sync_knowledge:
        parser.error("--publish / --retry-failed 必须与 --sync-knowledge 一起使用")
    if args.sync_knowledge and not args.apply:
        parser.error("知识库同步需要 --apply；预览模式不会写入")
    from app.database import Base, SessionLocal, engine
    from app.services.catalogue_import import CatalogueRecord, import_records
    import app.models  # noqa: F401

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not 1 <= len(payload) <= 500:
        parser.error("输入应为包含1至500条已核对书目的 JSON 数组")
    records = [CatalogueRecord.model_validate(item) for item in payload]
    if args.apply:
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        admin_id = None
        if args.sync_knowledge:
            from sqlalchemy import select
            from app.models.users import User
            admin = db.scalar(select(User).where(User.username == args.admin, User.role == "admin", User.status == 1))
            if admin is None:
                parser.error("未找到有效管理员")
            admin_id = admin.id
        result = import_records(db, records, dry_run=not args.apply)
        if args.sync_knowledge:
            from app.services.catalogue_knowledge import sync_book
            for item in result:
                item["knowledge"] = asyncio.run(sync_book(db, item["book_id"], admin_id,
                    publish=args.publish, retry_failed=args.retry_failed))
    print(json.dumps({"applied": args.apply, "records": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
