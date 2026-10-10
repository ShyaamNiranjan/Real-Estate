"""Scheduled jobs. Run with `python -m app.jobs <name>` from a scheduler (cron, hosting scheduler)."""

import logging
import sys

from app.analytics import send_weekly_summaries
from app.billing import run_lifecycle
from app.exports import run_exports

JOBS = {"weekly": send_weekly_summaries, "lifecycle": run_lifecycle, "exports": run_exports}


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in JOBS:
        sys.exit(f"usage: python -m app.jobs [{'|'.join(JOBS)}]")
    result = JOBS[name]()
    logging.info("%s done: %s", name, result)


if __name__ == "__main__":
    main()
