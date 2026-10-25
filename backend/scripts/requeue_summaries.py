"""Queue a fresh summary pass for processed events after the summary version changes.

Dry run by default. Stored summaries stay in place until the new pass replaces them, user data
(insights, chats, feedback) is never touched, dependent cards become stale through the event version.
"""

import argparse

from app.db import session_factory
from app.services.resummarize import requeue_summaries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with session_factory()() as db:
        count = requeue_summaries(db, args.version, args.apply)
        if args.apply:
            db.commit()
    print(f"events: {count}, queued: {count if args.apply else 0}")


if __name__ == "__main__":
    main()
