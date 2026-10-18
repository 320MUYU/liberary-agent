"""Preview the additive users.token_version upgrade; pass --apply to execute."""

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy import Integer, inspect, text


def upgrade(engine, *, apply=False):
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        raise RuntimeError("users table is missing; initialize the database before upgrading")
    column = next((c for c in inspector.get_columns("users") if c["name"] == "token_version"), None)
    if column is not None:
        if not isinstance(column["type"], Integer) or column["nullable"]:
            raise RuntimeError("users.token_version must be a nonnullable integer; inspect the existing schema")
        return []
    changes = ["ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"]
    if apply:
        with engine.begin() as connection:
            for statement in changes:
                connection.execute(text(statement))
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.database import engine
    print(json.dumps({"applied": args.apply, "statements": upgrade(engine, apply=args.apply)}, indent=2))


if __name__ == "__main__":
    main()
