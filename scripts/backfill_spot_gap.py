"""One-off backfill for the hourly SpotCandle gap found while running tasks.md
8.3: archiver_loop.py stopped cleanly (no crash, just never restarted) after a
normal pass on 2026-07-23 06:34 — everything after that point is missing
hourly BTC-USD/ETH-USD spot candles, which trend_scalp/level_break need via
StrategyContext.spot_bars. This is a live, unauthenticated, read-only call to
Coinbase's public candle endpoint (no Kalshi involved) — same fetch function
fetch_historical.py already uses, just with a wider `hours` window than the
default 60 days so it reaches back across the gap.

Usage:
  uv run python scripts/backfill_spot_gap.py --hours 2000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from loguru import logger  # noqa: E402
from sqlalchemy import select  # noqa: E402

from kalshi_bot.config.settings import get_settings  # noqa: E402
from kalshi_bot.data.crypto_feeds.spot_klines import fetch_coinbase_hourly  # noqa: E402
from kalshi_bot.storage import create_all_tables, get_engine, get_session_factory  # noqa: E402
from kalshi_bot.storage.models import SpotCandle  # noqa: E402

SYMBOLS = ["BTC-USD", "ETH-USD"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=2000)
    args = parser.parse_args()

    settings = get_settings()
    engine = get_engine(settings)
    create_all_tables(engine)
    session = get_session_factory(engine)()

    existing: set[tuple[str, str, int]] = set(
        session.execute(select(SpotCandle.exchange, SpotCandle.symbol, SpotCandle.open_ts)).tuples()
    )

    total_inserted = 0
    for symbol in SYMBOLS:
        rows = fetch_coinbase_hourly(symbol, hours=args.hours)
        inserted = 0
        for row in rows:
            key = (row["exchange"], row["symbol"], row["open_ts"])
            if key not in existing:
                session.add(SpotCandle(**row))
                existing.add(key)
                inserted += 1
        session.commit()
        total_inserted += inserted
        logger.info("{}: {} new hourly spot rows inserted", symbol, inserted)

    logger.info("Backfill done: {} total new rows", total_inserted)


if __name__ == "__main__":
    main()
