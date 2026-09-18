"""Bounded, foreground synthetic-BRTI composition over a window
(brti-constituent-history §5).

Reads constituent trades already backfilled by `backfill_constituents.py`,
composes them into a one-second reconstructed series, persists it to
`reconstructed_index_observations`, and prints contributor coverage. Never
writes to `brti_observations`.

Usage:
  uv run python scripts/compose_synthetic_brti.py --asset BTC \
      --start 2026-01-01T00:00:00 --end 2026-01-01T01:00:00
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kalshi_bot.config.settings import Settings
from kalshi_bot.data.external_sources import (
    ACTIVE_CRYPTO_ASSETS,
    coinbase_constituent_instrument,
    kraken_constituent_instrument,
)
from kalshi_bot.data.synthetic_brti import (
    ConstituentTrade,
    compose_synthetic_brti,
    persist_reconstructed_seconds,
)
from kalshi_bot.storage.db import create_all_tables, get_engine, get_session_factory
from kalshi_bot.storage.models import NormalizedAggregateTrade


def _parse_ts(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp())


def _load_trades(session, *, venue: str, instrument, start_ts: int, end_ts: int):
    rows = (
        session.query(NormalizedAggregateTrade)
        .filter(
            NormalizedAggregateTrade.source == venue,
            NormalizedAggregateTrade.native_symbol == instrument.native_symbol,
            NormalizedAggregateTrade.observed_at >= start_ts * 1_000,
            NormalizedAggregateTrade.observed_at < end_ts * 1_000,
        )
        .all()
    )
    return tuple(
        ConstituentTrade(instrument=instrument, observed_at_ms=row.observed_at, price=row.price)
        for row in rows
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", choices=sorted(ACTIVE_CRYPTO_ASSETS), required=True)
    parser.add_argument("--start", required=True, help="ISO 8601, e.g. 2026-01-01T00:00:00")
    parser.add_argument("--end", required=True, help="ISO 8601, exclusive")
    parser.add_argument("--db", type=Path, default=Path("data/kalshi_bot.db"))
    args = parser.parse_args()

    start_ts, end_ts = _parse_ts(args.start), _parse_ts(args.end)
    if start_ts >= end_ts:
        raise SystemExit("--start must precede --end")

    engine = get_engine(Settings(db_path=args.db))
    create_all_tables(engine)
    with get_session_factory(engine)() as session:
        trades_by_venue = {
            "kraken": _load_trades(
                session,
                venue="kraken",
                instrument=kraken_constituent_instrument(args.asset),
                start_ts=start_ts,
                end_ts=end_ts,
            ),
            "coinbase": _load_trades(
                session,
                venue="coinbase",
                instrument=coinbase_constituent_instrument(args.asset),
                start_ts=start_ts,
                end_ts=end_ts,
            ),
        }
        result = compose_synthetic_brti(trades_by_venue, start_ts=start_ts, end_ts=end_ts)
        written = persist_reconstructed_seconds(session, result, composed_at=int(time.time()))
        session.commit()

    total_seconds = end_ts - start_ts
    contributor_histogram: dict[int, int] = {}
    for second in result.seconds:
        contributor_histogram[second.contributor_count] = (
            contributor_histogram.get(second.contributor_count, 0) + 1
        )
    print(
        {
            "asset": args.asset,
            "window_seconds": total_seconds,
            "seconds_composed": len(result.seconds),
            "gap_seconds": len(result.gap_seconds),
            "rows_written": written,
            "contributor_histogram": contributor_histogram,
            "refusals": [
                {"venue": r.venue, "reason": r.reason} for r in result.refusals
            ],
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
