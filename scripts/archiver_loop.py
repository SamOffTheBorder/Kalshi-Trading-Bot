"""Persistent archiver loop — run this in its own visible window.

Repeatedly archives crypto + weather series at 1-minute granularity, plus spot
klines, then sleeps. Designed to run for hours/days in a console window you can
glance at (progress prints) and close anytime (Ctrl+C or just close the window
— nothing is lost; every fetch is resumable).

Every pass is also logged to logs/archiver_loop.log (rotating, kept outside the
console window) so a silent death leaves evidence instead of a mystery — the
console window has died silently more than once with nothing to diagnose why.

Usage:
  uv run python scripts/archiver_loop.py                  # default: every 30 min
  uv run python scripts/archiver_loop.py --interval 600    # every 10 min
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

PYTHON = sys.executable
LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "archiver_loop.log"
# Weather series first: dirt-cheap to archive (~6 markets/day each, EVERY strike
# trades — spike 2026-07-16: KXHIGHLAX 5.5M contracts/wk, KXHIGHNY 1.4M) and they
# are the designated pivot family if crypto validation fails. Crypto after.
SERIES = [
    "KXHIGHNY",
    "KXHIGHLAX",
    "KXHIGHMIA",
    "KXHIGHCHI",
    "KXHIGHAUS",
    "KXHIGHDEN",
    "KXHIGHPHIL",
    "KXLOWTOKC",
    "KXLOWTDC",
    "KXBTC",
    "KXBTCD",
    "KXETH",
    "KXETHD",
]

logger = logging.getLogger("archiver_loop")


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = RotatingFileHandler(LOG_PATH, maxBytes=5_000_000, backupCount=3)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)


def run(cmd: list[str]) -> None:
    logger.info("$ %s", " ".join(cmd))
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.stdout:
        logger.info(result.stdout.rstrip())
    if result.returncode != 0:
        stderr_tail = (result.stderr or "").rstrip()[-2000:]
        logger.warning("exit code %d: %s", result.returncode, stderr_tail)


def one_pass() -> None:
    logger.info("=" * 70)
    logger.info("Archive pass starting")
    logger.info("=" * 70)

    # Series with the least coverage go first, so a slow/rate-limited run
    # still makes progress on the series that need it most before circling
    # back to KXBTC's much larger backlog.
    for series in SERIES:
        run([PYTHON, "scripts/fetch_historical.py", "--series", series, "--period", "1"])

    run([PYTHON, "scripts/fetch_historical.py", "--series", "--spot"])

    logger.info("=" * 70)
    logger.info("Coverage after this pass:")
    logger.info("=" * 70)
    run([PYTHON, "scripts/fetch_historical.py", "--report", "--period", "1"])

    logger.info("Pass complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval", type=int, default=1800, help="seconds between passes (default 30 min)"
    )
    args = parser.parse_args()

    setup_logging()
    logger.info(
        "Kalshi archiver loop starting (log: %s). Close this window anytime to stop — "
        "safe, resumable.",
        LOG_PATH,
    )
    while True:
        try:
            one_pass()
        except KeyboardInterrupt:
            logger.info("Stopped.")
            return
        except Exception:
            # A crash inside one_pass must never silently kill the whole loop —
            # that's exactly the failure mode this loop exists to avoid. Log the
            # full traceback and keep going after the normal interval.
            logger.error("Archive pass crashed:\n%s", traceback.format_exc())
        logger.info("Sleeping %ds (Ctrl+C or close window to stop)...", args.interval)
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info("Stopped.")
            return


if __name__ == "__main__":
    main()
