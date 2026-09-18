"""Quick 'is capture working?' snapshot.

Run this in a separate terminal while start_all_capture.bat is going. It reads
the database read-only and prints row counts and how fresh each feed is, so you
can tell at a glance whether data is still landing.

  uv run python scripts/capture_status.py
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

DB = Path("data/kalshi_bot.db")


def _age(ts: int | None, now: int) -> str:
    if ts is None:
        return "never"
    ts = int(ts)
    # A few tables store retrieved_at in epoch milliseconds; normalize to seconds.
    if ts > 100_000_000_000:
        ts //= 1000
    d = now - ts
    if d < 90:
        return f"{d}s ago"
    if d < 5_400:
        return f"{d // 60}m ago"
    if d < 172_800:
        return f"{d // 3600}h ago"
    return f"{d // 86_400}d ago"


def main() -> int:
    if not DB.exists():
        print(f"no database at {DB.resolve()}")
        return 1

    now = int(time.time())
    # Read-only, and don't block on a writer's lock -- capture holds it often.
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    conn.execute("PRAGMA busy_timeout = 8000")

    def one(sql: str) -> tuple:
        for attempt in range(4):
            try:
                return conn.execute(sql).fetchone() or (0, None)
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc) and attempt < 3:
                    time.sleep(1.5)
                    continue
                return (f"ERR {exc}", None)
        return (0, None)

    print(f"\n  capture status @ {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    # --- Phase 1: backfillable history -------------------------------------
    print("  PHASE 1  backfillable history (fills once, then stable)")
    bars = one(
        "select count(*), max(retrieved_at) from normalized_market_bars where source='binance'"
    )
    by_mt = conn.execute(
        "select market_type, count(*) from normalized_market_bars "
        "where source='binance' group by 1 order by 1"
    ).fetchall()
    detail = ", ".join(f"{m}={n:,}" for m, n in by_mt) or "none"
    print(f"    binance bars ...... {bars[0]:>12,}   ({detail})")
    print(f"                         last import {_age(bars[1], now)}")

    disc = one("select count(*), max(checked_at) from discovery_results")
    print(f"    crypto discovery .. {disc[0]:>12}   rows, checked {_age(disc[1], now)}")

    sd = one(
        "select count(*), max(observed_at) from sports_market_discovery"
    )
    se = one("select count(*) from sports_market_discovery where eligible=1")
    print(
        f"    sports discovery .. {sd[0]:>12,}   rows ({se[0]:,} eligible), "
        f"seen {_age(sd[1], now)}"
    )

    # --- Phase 2: live-only feeds ----------------------------------------
    print("\n  PHASE 2  live-only feeds (should keep advancing while running)")
    feeds = [
        ("BRTI / CF indices", "brti_observations", "observed_at"),
        ("perp marks", "perp_mark_observations", "observed_at"),
        ("perp funding", "perp_funding_observations", "observed_at"),
        ("KXBTC15M candles", "candles", "end_period_ts"),
        ("sports candles", "sports_candles", "end_period_ts"),
    ]
    for label, table, tscol in feeds:
        row = one(f"select count(*), max({tscol}) from {table}")
        print(f"    {label:<18} {row[0]:>12,}   rows, newest {_age(row[1], now)}")

    print()
    print("  reading: PHASE 1 counts climb during the first run, then hold steady.")
    print("           PHASE 2 'newest' should be seconds/minutes ago while the")
    print("           poll is active; hours/days ago means that feed is stalled.")
    print()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
