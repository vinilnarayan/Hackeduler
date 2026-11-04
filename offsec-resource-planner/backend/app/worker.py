"""Background worker: email outbox delivery, pending-reservation expiry, completion.

Run with:  python -m app.worker            (loop)
           python -m app.worker --once     (single pass, e.g. from cron)
"""
from __future__ import annotations

import argparse
import logging
import signal
import time

from .config import get_settings
from .db import SessionLocal
from .services import booking_service, email_sender

log = logging.getLogger("orp.worker")
_running = True


def run_once() -> dict:
    result: dict = {}
    db = SessionLocal()
    try:
        result["expired"] = len(booking_service.expire_stale_pending(db))
        db.commit()
        result["deactivated"] = len(booking_service.apply_scheduled_deactivations(db))
        db.commit()
        result["completed"] = len(booking_service.complete_past_bookings(db))
        db.commit()
        result["email"] = email_sender.process_outbox(db)
    except Exception:
        db.rollback()
        log.exception("worker pass failed")
    finally:
        db.close()
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.once:
        log.info("pass: %s", run_once())
        return

    def stop(*_):
        global _running
        _running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    interval = get_settings().worker_interval_seconds
    log.info("worker started (interval %ss)", interval)
    while _running:
        r = run_once()
        if any(r.get(k) for k in ("expired", "completed", "deactivated")) or (r.get("email") and any(r["email"].values())):
            log.info("pass: %s", r)
        for _ in range(interval):
            if not _running:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
