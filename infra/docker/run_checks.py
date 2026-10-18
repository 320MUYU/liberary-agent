"""Run backend checks against randomly named test databases, never the business schema."""

import json
import logging
import os
import sys
import unittest

sys.path.insert(0, "/app")


def main():
    # Read the test server credential on stdin so it never appears in process args.
    credentials = json.load(sys.stdin)
    # Keep the already validated runtime singleton, but let Settings(_env_file=None)
    # tests exercise defaults instead of inheriting this container's feature flags.
    from app.config import Settings
    for key in Settings.model_fields:
        if key not in {"DATABASE_URL", "JWT_SECRET_KEY", "JWT_EXPIRE_HOURS", "JWT_ALGORITHM"}:
            os.environ.pop(key, None)
    os.environ.pop("EMBEDDING_DIMENSION", None)
    from sqlalchemy.engine import URL
    url = URL.create("mysql+pymysql", username="root", password=credentials["mysql_root_password"],
        host="mysql", port=3306, database="unused_test_source")
    os.environ.update(RUN_LIBRARY_MYSQL_TEST="1", RUN_CHROMA_HTTP_SMOKE="1",
        MYSQL_LIBRARY_TEST_URL=url.render_as_string(hide_password=False))
    logging.disable(logging.CRITICAL)
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover("tests"))
    summary = {"total": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "skipped": len(result.skipped), "passed": result.wasSuccessful()}
    print(json.dumps(summary))
    raise SystemExit(not result.wasSuccessful())


if __name__ == "__main__":
    main()
