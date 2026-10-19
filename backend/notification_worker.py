"""Independent reader reminder worker; successful scans update a health heartbeat."""

import argparse
import json
import logging
import os
from pathlib import Path
import signal
from threading import Event
import time

from app.database import SessionLocal
from app.services.notification_reminders import generate_reminders

HEARTBEAT = Path("data/notifications/heartbeat.json")
logger = logging.getLogger(__name__)


def run_once():
    with SessionLocal() as db:
        count = generate_reminders(db)
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    pending = HEARTBEAT.with_suffix(".tmp")
    pending.write_text(json.dumps({"pid": os.getpid(), "success_at": time.time(), "created": count}))
    pending.replace(HEARTBEAT)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.once:
        run_once()
        return
    stopped = Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    while not stopped.is_set():
        try:
            count = run_once()
            logger.info("Reminder scan complete: %s new notifications", count)
        except Exception:
            logger.exception("Reminder scan failed; retrying in 60 seconds")
        stopped.wait(60)


if __name__ == "__main__":
    main()
