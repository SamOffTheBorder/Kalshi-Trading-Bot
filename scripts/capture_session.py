"""Deliberate foreground capture/import for KXBTC15M validation data.

This command never schedules itself. ``--import-jsonl`` accepts operator-exported
observations with the schema of the corresponding storage table. Kalshi market
and candle capture uses only the unauthenticated public client.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
import uuid
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from kalshi_bot.data.kalshi.client import KalshiPublicClient  # noqa: E402
from kalshi_bot.data.kalshi.parse import parse_candle, parse_market  # noqa: E402
from kalshi_bot.storage import (  # noqa: E402
    BRTIObservation,
    Candle,
    KalshiMarket,
    OrderBookSnapshot,
    PublicTrade,
    create_all_tables,
    get_engine,
    get_session_factory,
)

KINDS = {"brti": BRTIObservation, "l2": OrderBookSnapshot, "trade": PublicTrade}


def import_jsonl(session, path: Path, kind: str, session_id: str) -> int:
    model = KINDS[kind]
    count = 0
    now = int(time.time())
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            row.setdefault("capture_session_id", session_id)
            row.setdefault("fetched_at", now)
            row.setdefault("provenance", {"operator_run": True, "import_file": str(path)})
            session.add(model(**row))
            count += 1
    session.commit()
    return count


def gap_report(session, kind: str, *, period_seconds: int | None = None) -> dict[str, object]:
    """Summarize first/last timestamps, gaps, and capture sessions."""
    model = KINDS[kind]
    rows = session.execute(select(model).order_by(model.observed_at)).scalars().all()
    timestamps = [r.observed_at for r in rows]
    gaps = []
    if period_seconds:
        gaps = [(a, b, b - a) for a, b in itertools.pairwise(timestamps) if b - a > period_seconds]
    return {
        "kind": kind,
        "first_ts": min(timestamps) if timestamps else None,
        "last_ts": max(timestamps) if timestamps else None,
        "rows": len(rows),
        "gap_count": len(gaps),
        "gaps": gaps,
        "capture_sessions": sorted({r.capture_session_id for r in rows if r.capture_session_id}),
    }


def capture_kxbtc15m(session, *, start_ts: int, end_ts: int, period_minutes: int,
                     max_markets: int, session_id: str) -> tuple[int, int]:
    markets = candles = 0
    now = int(time.time())
    with KalshiPublicClient(max_reads_per_second=8) as client:
        for raw in client.iter_markets(series_ticker="KXBTC15M", status="settled",
                                       min_close_ts=start_ts, max_close_ts=end_ts):
            if max_markets and markets >= max_markets:
                break
            endpoint = "/markets?series_ticker=KXBTC15M&status=settled"
            parsed = parse_market(raw, series_ticker="KXBTC15M", capture_session_id=session_id,
                                  source_endpoint=endpoint, fetched_at=now)
            session.merge(KalshiMarket(**parsed))
            raw_candles = client.get_candlesticks(
                "KXBTC15M", raw["ticker"], start_ts=parsed["open_ts"],
                end_ts=parsed["close_ts"], period_minutes=period_minutes
            )
            for item in raw_candles:
                session.add(Candle(**parse_candle(
                    item, market_ticker=raw["ticker"], series_ticker="KXBTC15M",
                    period_minutes=period_minutes, capture_session_id=session_id,
                    source_endpoint=f"/series/KXBTC15M/markets/{raw['ticker']}/candlesticks",
                    fetched_at=now)))
            markets += 1
            candles += len(raw_candles)
    session.commit()
    return markets, candles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-jsonl", type=Path)
    parser.add_argument("--kind", choices=sorted(KINDS))
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--start-ts", type=int)
    parser.add_argument("--end-ts", type=int)
    parser.add_argument("--period", type=int, default=1)
    parser.add_argument("--max-markets", type=int, default=0)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    if args.import_jsonl and not args.kind:
        parser.error("--kind is required with --import-jsonl")
    if args.capture and (args.start_ts is None or args.end_ts is None):
        parser.error("--capture requires --start-ts and --end-ts")
    engine = get_engine()
    create_all_tables(engine)
    session_id = f"manual-{uuid.uuid4().hex}"
    with get_session_factory(engine)() as session:
        if args.import_jsonl:
            print(f"imported={import_jsonl(session, args.import_jsonl, args.kind, session_id)}")
        if args.capture:
            print("capture=", capture_kxbtc15m(
                session, start_ts=args.start_ts, end_ts=args.end_ts,
                period_minutes=args.period, max_markets=args.max_markets, session_id=session_id
            ))
        if args.report:
            for kind in KINDS:
                print(json.dumps(gap_report(session, kind), sort_keys=True))


if __name__ == "__main__":
    main()
