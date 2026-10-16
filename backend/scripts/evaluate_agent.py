"""Offline borrowing-agent harness. Uses isolated fixtures and fake model decisions.

No cloud calls or live business writes. This validates execution contracts, not
the real model's language understanding. Run MySQL concurrency tests separately.
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
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.environ.update(DATABASE_URL="sqlite:///:memory:", JWT_SECRET_KEY="agent-harness-test-only-secret-key",
        JWT_EXPIRE_HOURS="24", JWT_ALGORITHM="HS256", AGENT_TOOL_TRANSPORT="local",
        RAG_ENABLED="false", RERANK_ENABLED="false")
    logging.disable(logging.CRITICAL)
    modules = ["tests.test_agent_" + name for name in ("tools", "graph", "actions", "api", "mcp")]
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
            "lost write response replay", "MCP capability authorization"]}
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    if not result.wasSuccessful():
        print(output.getvalue(), file=sys.stderr)
    return int(not result.wasSuccessful())


if __name__ == "__main__":
    raise SystemExit(main())
