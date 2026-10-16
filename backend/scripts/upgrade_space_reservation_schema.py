"""Preview the non-destructive MySQL reservation compatibility upgrade; --apply executes it."""

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy import String, inspect, text


def upgrade(engine, *, apply=False):
    if engine.dialect.name != "mysql":
        raise RuntimeError("This compatibility upgrade requires MySQL")
    inspector = inspect(engine)
    if not inspector.has_table("reservations"):
        raise RuntimeError("reservations table is missing; initialize the database first")
    columns = {column["name"]: column for column in inspector.get_columns("reservations")}
    clauses = []
    for name in ("note", "review_note"):
        if name not in columns or not isinstance(columns[name]["type"], String):
            raise RuntimeError(f"Unexpected schema for reservations.{name}; no changes applied")
        column = columns[name]
        kind = column["type"].copy()
        widen = name == "review_note" and kind.length is not None and kind.length < 500
        if widen:
            kind.length = 500
        if column["nullable"] and not widen:
            continue
        clause = f"MODIFY COLUMN {name} {kind.compile(dialect=engine.dialect)} NULL"
        if column.get("default") is not None:
            clause += " DEFAULT " + column["default"]
        if column.get("comment"):
            literal = engine.dialect.statement_compiler(engine.dialect, None).render_literal_value(column["comment"], String())
            clause += " COMMENT " + literal
        clauses.append(clause)
    statements = ["ALTER TABLE reservations " + ", ".join(clauses)] if clauses else []
    if apply and statements:
        with engine.begin() as connection:
            connection.execute(text(statements[0]))
    return statements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.database import engine
    print(json.dumps({"applied": args.apply, "statements": upgrade(engine, apply=args.apply)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
