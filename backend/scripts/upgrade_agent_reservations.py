"""Preview/create the independent Agent reservation table; never alters old tables."""

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy import inspect


def upgrade(engine, *, apply=False):
    from app.models.agent import AgentReservationAction
    from sqlalchemy.schema import CreateTable
    table = AgentReservationAction.__table__
    if inspect(engine).has_table(table.name):
        return []
    statements = [str(CreateTable(table).compile(engine))]
    if apply:
        table.create(engine, checkfirst=True)
    return statements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import app.models  # noqa: F401
    from app.database import engine
    print(json.dumps({"applied": args.apply, "statements": upgrade(engine, apply=args.apply)}, indent=2))


if __name__ == "__main__":
    main()
