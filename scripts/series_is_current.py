"""Exit 0 ("skip me") if a series' candles already reach the requested
end-of-window; exit 1 ("capture me") otherwise.

Read-only, one-shot, foreground -- used by start_capture.bat right before
each per-series capture_session.py --capture step so a series that is
already caught up for this cycle's rolling window isn't re-fetched.

    uv run python scripts/series_is_current.py --series KXBTC15M --end-ts 123 --period 15
    if %ERRORLEVEL% EQU 0 (skip) else (run the capture)

"Current" means: at least one candle row exists whose end_period_ts is
within one period of --end-ts. A series with zero rows is never current
(so a series that has never captured successfully, e.g. a market with no
open contracts yet, keeps getting retried rather than silently skipped
forever).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/kalshi_bot.db"))
    parser.add_argument("--series", required=True, help="series_ticker, e.g. KXBTC15M")
    parser.add_argument("--end-ts", type=int, required=True, help="requested window end, epoch s")
    parser.add_argument(
        "--period", type=int, required=True,
        help="candle period in minutes (15 for *15M series, 60 for hourly strike-ladder series)",
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"no database at {args.db.resolve()} -- capture it", file=sys.stderr)
        return 1

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=10)
    try:
        row = conn.execute(
            "select max(end_period_ts) from candles where series_ticker = ?",
            (args.series,),
        ).fetchone()
    finally:
        conn.close()

    newest = row[0] if row else None
    if newest is None:
        print(f"{args.series}: no candles captured yet -- capture it")
        return 1

    stale_by = args.end_ts - newest
    tolerance = args.period * 60
    if stale_by <= tolerance:
        print(f"{args.series}: current (newest candle {stale_by}s behind window end) -- skip")
        return 0
    print(f"{args.series}: stale by {stale_by}s (tolerance {tolerance}s) -- capture it")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
