"""Preview additive Agent columns; pass --apply to upgrade an existing database."""

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy import inspect, text


def upgrade(engine, *, apply=False):
    changes = []
    for table, column in (("agent_runs", "task_type"), ("agent_actions", "action_type")):
        inspector = inspect(engine)
        if not inspector.has_table(table):
            raise RuntimeError("Agent tables are missing; initialize the database before upgrading")
        if column not in {item["name"] for item in inspector.get_columns(table)}:
            changes.append(f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR(20) NOT NULL DEFAULT 'borrow'")
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
