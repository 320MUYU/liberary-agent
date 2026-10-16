"""Offline borrowing-agent harness. Uses isolated fixtures and fake model decisions.

Default mode makes no cloud calls or live business writes. --live-discovery
reads the real catalogue and calls configured embedding/rerank services, without
creating borrowing records. Run MySQL concurrency tests separately.
"""

import argparse
import io
import json
import logging
import os
from pathlib import Path
import sys
import time
import unittest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--live-discovery", action="store_true",
        help="Read real catalogue with configured embedding/rerank services; no borrowing writes")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    if args.live_discovery:
        return live_discovery(args.output)
    os.environ.update(DATABASE_URL="sqlite:///:memory:", JWT_SECRET_KEY="agent-harness-test-only-secret-key",
        JWT_EXPIRE_HOURS="24", JWT_ALGORITHM="HS256", AGENT_TOOL_TRANSPORT="local",
        RAG_ENABLED="false", RERANK_ENABLED="false")
    logging.disable(logging.CRITICAL)
    modules = ["tests.test_agent_" + name for name in ("tools", "graph", "actions", "api", "mcp", "discovery")]
    modules.append("tests.test_book_discovery")
    output = io.StringIO()
    started = time.monotonic()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromNames(modules))
    report = {"mode": "offline_contracts", "synthetic": True, "real_model_evaluated": False,
        "total": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "skipped": len(result.skipped), "elapsed_seconds": round(time.monotonic() - started, 3),
        "failed_cases": [case.id() for case, _ in result.failures + result.errors],
        "passed": result.wasSuccessful(),
        "coverage": ["read-only tools", "bounded tool loop", "persistent interrupt recovery",
            "confirmation binding", "expiry and ownership", "atomic rollback",
            "lost write response replay", "MCP capability authorization", "three category discovery",
            "edition source ownership", "publication changes", "live inventory refresh", "retrieval degradation"]}
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    if not result.wasSuccessful():
        print(output.getvalue(), file=sys.stderr)
    return int(not result.wasSuccessful())


def live_discovery(output):
    from sqlalchemy import select, func
    from app.database import SessionLocal
    from app.models.book_sources import BookSource
    from app.models.loans import Loan
    from app.services.book_discovery import discover_books
    from app.services.knowledge_service import get_source

    cases = [("找多智能体相关的书", "AI / Agent"),
             ("推荐一些历史书", "历史图书"), ("推荐儿童图书", "儿童图书")]
    report = {"mode": "live_discovery", "synthetic": False, "real_model_evaluated": False, "cases": []}
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(Loan))
        for query, expected in cases:
            started = time.monotonic()
            result = discover_books(db, query, mode="topic")
            sources_valid = True
            previews = []
            for book in result["books"]:
                for source in book["sources"]:
                    owner = db.scalar(select(BookSource.book_id).where(
                        BookSource.knowledge_document_id == source["document_id"]))
                    preview = get_source(db, source["chunk_id"])
                    valid = owner == book["id"] and preview["document_id"] == source["document_id"]
                    sources_valid = sources_valid and valid
                    previews.append({"book_id": book["id"], "chunk_id": source["chunk_id"], "valid": valid})
            report["cases"].append({"query": query, "expected_category": expected,
                "category_hit": any(b["category"] == expected for b in result["books"]),
                "source_checks": previews, "sources_valid": sources_valid,
                "elapsed_seconds": round(time.monotonic() - started, 3), **result})
        db.rollback()
        report["loans_unchanged"] = before == db.scalar(select(func.count()).select_from(Loan))
    report["passed"] = report["loans_unchanged"] and all(
        case["category_hit"] and case["source_checks"] and case["sources_valid"]
        and case["retrieval"]["status"] == "ok" for case in report["cases"])
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
