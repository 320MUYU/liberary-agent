"""Preview/create the inbox table without backfilling historical approvals."""

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy import inspect
from sqlalchemy.schema import CreateIndex, CreateTable


def upgrade(engine, *, apply=False):
    from app.models.notification import Notification
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        raise RuntimeError("users table is missing; initialize the database before upgrading")
    table = Notification.__table__
    if inspector.has_table(table.name):
        columns = {c["name"] for c in inspector.get_columns(table.name)}
        unique = [set(c["column_names"]) for c in inspector.get_unique_constraints(table.name)]
        if not set(table.columns.keys()).issubset(columns) or {"user_id", "event_key"} not in unique:
            raise RuntimeError("reader_notifications has an incompatible schema; inspect it before upgrading")
        return []
    statements = [str(CreateTable(table).compile(engine))]
    statements.extend(str(CreateIndex(index).compile(engine)) for index in sorted(table.indexes, key=lambda i: i.name))
    if apply:
        table.create(engine, checkfirst=True)
    return statements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import app.models
    from app.database import engine
    print(json.dumps({"applied": args.apply, "statements": upgrade(engine, apply=args.apply)}, indent=2))


if __name__ == "__main__":
    main()
