"""Run separately from the API: python knowledge_worker.py [--once]."""

import argparse
import time

import app.models  # Register all tables without importing the API's startup side effects.
from app.config import settings
from app.database import SessionLocal
from app.services.knowledge_ingestion import process_next_job


def main():
    parser = argparse.ArgumentParser(description="知识库持久索引任务 worker")
    parser.add_argument("--once", action="store_true", help="处理最多一个任务后退出")
    args = parser.parse_args()
    if not settings.RAG_ENABLED:
        parser.error("请先在 backend/.env 启用 RAG_ENABLED")
    while True:
        with SessionLocal() as db:
            processed = process_next_job(db)
        if args.once:
            return
        if not processed:
            time.sleep(2)


if __name__ == "__main__":
    main()
