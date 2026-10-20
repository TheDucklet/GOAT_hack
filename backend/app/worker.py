import argparse
import logging
import time

from app.config import get_settings
from app.db import session_factory
from app.services.jobs import run_one, scheduler_tick

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run at most one queued job without scheduling")
    parser.add_argument("--run-seconds", type=float, help="Stop the worker after a bounded smoke check")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.once:
        run_one()
        return
    stop_at = time.monotonic() + args.run_seconds if args.run_seconds else None
    while stop_at is None or time.monotonic() < stop_at:
        try:
            with session_factory()() as db, db.begin():
                scheduler_tick(db)
            if not run_one():
                time.sleep(get_settings().worker_poll_seconds)
        except KeyboardInterrupt:
            return
        except Exception:
            # Do not expose database URLs, provider inputs or source contents in logs.
            logger.error("worker_iteration_failed")
            time.sleep(get_settings().worker_poll_seconds)


if __name__ == "__main__":
    main()
