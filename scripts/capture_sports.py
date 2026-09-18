"""Operator-run, bounded sports discovery/capture (read-only).

This command performs one foreground action and exits. It never schedules,
restarts, backfills unavailable observations, or places paper/live orders.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kalshi_bot.config.settings import Settings
from kalshi_bot.data.kalshi.client import KalshiPublicClient
from kalshi_bot.data.sports.capture import capture_report, capture_sports
from kalshi_bot.data.sports.discovery import DiscoveryConfig, discover_sports
from kalshi_bot.storage.db import create_all_tables, get_engine, get_session_factory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/kalshi_bot.db"))
    parser.add_argument(
        "--series",
        action="append",
        required=True,
        help="sports series ticker; repeatable or comma-separated",
    )
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--start-ts", type=int)
    parser.add_argument("--end-ts", type=int)
    parser.add_argument("--period", type=int, default=1)
    parser.add_argument("--max-spread-cents", type=int, default=20)
    parser.add_argument("--min-depth", type=float, default=1.0)
    parser.add_argument("--min-open-interest", type=float, default=1.0)
    parser.add_argument("--no-order-books", action="store_true")
    parser.add_argument("--no-trades", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    if not any((args.discover, args.capture, args.report)):
        parser.error("choose at least one of --discover, --capture, or --report")
    if args.capture and (args.start_ts is None or args.end_ts is None):
        parser.error("--capture requires --start-ts and --end-ts")
    tickers = [part.strip() for chunk in args.series for part in chunk.split(",") if part.strip()]
    engine = get_engine(Settings(db_path=args.db))
    create_all_tables(engine)
    session_id = f"sports-manual-{uuid.uuid4().hex}"
    with KalshiPublicClient() as client, get_session_factory(engine)() as session:
        if args.discover:
            rows = discover_sports(
                session,
                client,
                series_tickers=tickers,
                session_id=session_id,
                config=DiscoveryConfig(
                    min_open_interest=args.min_open_interest,
                    min_top_size=args.min_depth,
                    max_spread_cents=args.max_spread_cents,
                ),
            )
            print(
                json.dumps(
                    {
                        "discovered": len(rows),
                        "eligible": sum(r.classification.eligible for r in rows),
                        "session_id": session_id,
                    },
                    sort_keys=True,
                )
            )
        if args.capture:
            result = capture_sports(
                session,
                client,
                market_tickers=None,
                start_ts=args.start_ts,
                end_ts=args.end_ts,
                period_minutes=args.period,
                include_order_books=not args.no_order_books,
                include_trades=not args.no_trades,
                session_id=session_id,
            )
            print(json.dumps({"capture": result.__dict__}, sort_keys=True))
        if args.report:
            print(json.dumps(capture_report(session), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
