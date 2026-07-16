"""Persistent archiver loop — run this in its own visible window.

Repeatedly archives all four crypto series at 1-minute granularity, plus spot
klines, then sleeps. Designed to run for hours/days in a console window you can
glance at (progress prints) and close anytime (Ctrl+C or just close the window
— nothing is lost; every fetch is resumable).

Usage:
  uv run python scripts/archiver_loop.py                  # default: every 30 min
  uv run python scripts/archiver_loop.py --interval 600    # every 10 min
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime

PYTHON = sys.executable
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


def run(cmd: list[str]) -> None:
    print(f"\n$ {' '.join(cmd)}")
    subprocess.run(cmd, check=False)


def one_pass(interval_s: int) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 70}\n[{stamp}] Archive pass starting\n{'=' * 70}")

    # Series with the least coverage go first, so a slow/rate-limited run
    # still makes progress on the series that need it most before circling
    # back to KXBTC's much larger backlog.
    for series in SERIES:
        run([PYTHON, "scripts/fetch_historical.py", "--series", series, "--period", "1"])

    run([PYTHON, "scripts/fetch_historical.py", "--series", "--spot"])

    print(f"\n{'=' * 70}\nCoverage after this pass:\n{'=' * 70}")
    run([PYTHON, "scripts/fetch_historical.py", "--report", "--period", "1"])

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{stamp}] Pass complete. Sleeping {interval_s}s (Ctrl+C or close window to stop)...")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval", type=int, default=1800, help="seconds between passes (default 30 min)"
    )
    args = parser.parse_args()

    print("Kalshi archiver loop starting. Close this window anytime to stop — safe, resumable.")
    try:
        while True:
            one_pass(args.interval)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
