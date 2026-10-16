"""Import a reviewed JSON array of public edition metadata; default is preview only."""

import argparse
import json
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--apply", action="store_true", help="写入书目；默认只预览")
    args = parser.parse_args()
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
        result = import_records(db, records, dry_run=not args.apply)
    print(json.dumps({"applied": args.apply, "records": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
