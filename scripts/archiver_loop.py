"""Manual, foreground archiver loop — run this in its own visible window.

Repeatedly archives BTC series (KXBTC/KXBTCD/KXBTC15M) at 1-minute
granularity, plus spot klines, then sleeps. Run it yourself, in the foreground,
for as long as you're actively working — close the window (Ctrl+C, or just
close it) whenever you're done; nothing is lost, every fetch is resumable.

By explicit decision (2026-09-04), this is NOT meant to run unattended: no
Windows Scheduled Task, no service, no auto-restart, no staleness alarm. A
missed session can lose data once it rolls off Kalshi's ~6-week window — that
trade-off is accepted in exchange for nothing ever running when you're not
watching it. See openspec/changes/v2-perps-scalping-and-frontend/proposal.md O1.

Every pass is also logged to logs/archiver_loop.log (rotating, kept outside the
console window) so a session's activity leaves evidence instead of a mystery.

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
# Crypto-only by explicit decision (2026-09-04): weather series are dropped from
# collection. Existing weather rows stay in the DB for reference; nothing new is
# fetched for them. See openspec/changes/v2-perps-scalping-and-frontend/proposal.md O1.
#
# BTC-only by further decision (2026-09-04): ETH series (KXETH/KXETHD) dropped
# too. Existing ETH rows stay in the DB for reference; nothing new is fetched.
#
# KXBTC15M (15-min "BTC up?" binary, the primary v2 scalping instrument) uses the
# same settled-candlestick pipeline as everything else here — verified live that
# a settled 15-min market's full 1-minute quote/OI history is retrievable the same
# as any other series (O3 in the same proposal). It needs its own pass at 1-minute
# period granularity (see below), not the 60-minute default used for the ladders.
SERIES = [
    "KXBTC",
    "KXBTCD",
    "KXBTC15M",
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
        run(
            [
                PYTHON,
                "scripts/fetch_historical.py",
                "--series",
                series,
                "--period",
                "1",
                "--time-budget",
                "180",  # a new series can't dominate a pass; resumes next pass
            ]
        )

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
