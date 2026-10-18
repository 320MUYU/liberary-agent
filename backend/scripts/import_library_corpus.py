"""Validate and import local, source-checked public library snapshots; preview by default."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--admin", default="admin")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if (args.publish or args.retry_failed) and not args.apply:
        parser.error("--publish / --retry-failed 需要 --apply")
    from sqlalchemy import select
    import app.models  # noqa: F401
    from app.database import SessionLocal, engine
    from app.models.users import User
    from app.services.library_corpus import load_manifest, sync_corpus
    from scripts.upgrade_library_corpus import upgrade

    manifest = load_manifest(args.manifest)
    if args.apply:
        upgrade(engine, apply=True)
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == args.admin, User.role == "admin", User.status == 1))
        if admin is None:
            parser.error("未找到有效管理员")
        report = asyncio.run(sync_corpus(db, manifest, args.snapshot_root, admin.id,
            apply=args.apply, publish=args.publish, retry_failed=args.retry_failed))
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
