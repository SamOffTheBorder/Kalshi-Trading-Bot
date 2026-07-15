"""Archive Kalshi settled markets + candlesticks (and spot klines) locally.

The public API is a ~6-week rolling window (see the change's notes.md), so
this script IS the deep archive: run it regularly (cron / Task Scheduler) and
the local DB accumulates history the API forgets.

Usage:
  uv run python scripts/fetch_historical.py                   # all four series, settled, 60m
  uv run python scripts/fetch_historical.py --series KXBTC --max-markets 200
  uv run python scripts/fetch_historical.py --spot            # also pull daily spot klines
  uv run python scripts/fetch_historical.py --report          # coverage report only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from kalshi_bot.data.crypto_feeds.spot_klines import (  # noqa: E402
    fetch_coinbase_daily,
    fetch_coinbase_hourly,
    fetch_kraken_daily,
)
from kalshi_bot.data.kalshi.client import KalshiPublicClient  # noqa: E402
from kalshi_bot.data.kalshi.coverage import coverage_report  # noqa: E402
from kalshi_bot.data.kalshi.parse import parse_candle, parse_market  # noqa: E402
from kalshi_bot.storage import (  # noqa: E402
    Candle,
    KalshiMarket,
    SpotCandle,
    create_all_tables,
    get_engine,
    get_session_factory,
)

DEFAULT_SERIES = ["KXBTC", "KXBTCD", "KXETH", "KXETHD"]
SPOT_SYMBOLS = ["BTC-USD", "ETH-USD"]


def fetch_series(
    client: KalshiPublicClient,
    session: Session,
    series_ticker: str,
    *,
    period_minutes: int,
    max_markets: int,
    skip_zero_volume: bool = True,
) -> tuple[int, int]:
    """Archive one series. Returns (markets_processed, candles_inserted)."""
    known_tickers = set(
        session.execute(
            select(KalshiMarket.ticker).where(KalshiMarket.series_ticker == series_ticker)
        ).scalars()
    )
    candled_tickers = set(
        session.execute(
            select(Candle.market_ticker.distinct()).where(
                Candle.series_ticker == series_ticker,
                Candle.period_minutes == period_minutes,
            )
        ).scalars()
    )

    markets_done = 0
    candles_inserted = 0
    for raw in client.iter_markets(series_ticker=series_ticker, status="settled"):
        if max_markets and markets_done >= max_markets:
            break
        row = parse_market(raw, series_ticker=series_ticker)
        ticker = row["ticker"]

        if ticker not in known_tickers:
            session.add(KalshiMarket(**row))
            known_tickers.add(ticker)

        # Most strikes per period are far OTM with zero lifetime volume —
        # candles for markets nobody ever traded are simulation fantasy and
        # cost one request each. Market metadata is still stored above.
        never_traded = not raw.get("volume")
        if skip_zero_volume and never_traded:
            markets_done += 1
            continue

        if ticker not in candled_tickers:
            raw_candles = client.get_candlesticks(
                series_ticker,
                ticker,
                start_ts=row["open_ts"],
                end_ts=row["close_ts"],
                period_minutes=period_minutes,
            )
            for rc in raw_candles:
                session.add(
                    Candle(
                        **parse_candle(
                            rc,
                            market_ticker=ticker,
                            series_ticker=series_ticker,
                            period_minutes=period_minutes,
                        )
                    )
                )
            candles_inserted += len(raw_candles)
            candled_tickers.add(ticker)

        markets_done += 1
        if markets_done % 200 == 0:
            session.commit()
            logger.info(
                "{}: {} markets processed, {} candles inserted",
                series_ticker,
                markets_done,
                candles_inserted,
            )
    session.commit()
    return markets_done, candles_inserted


def fetch_spot(session: Session) -> int:
    """Daily spot klines from both CF Benchmarks constituent sources."""
    existing: set[tuple[str, str, int]] = set(
        session.execute(select(SpotCandle.exchange, SpotCandle.symbol, SpotCandle.open_ts)).tuples()
    )
    inserted = 0
    for symbol in SPOT_SYMBOLS:
        for fetch in (fetch_kraken_daily, fetch_coinbase_daily, fetch_coinbase_hourly):
            try:
                rows = fetch(symbol)
            except Exception as exc:  # one source failing shouldn't kill the other
                logger.warning("{} fetch failed for {}: {}", fetch.__name__, symbol, exc)
                continue
            for row in rows:
                key = (row["exchange"], row["symbol"], row["open_ts"])
                if key not in existing:
                    session.add(SpotCandle(**row))
                    existing.add(key)
                    inserted += 1
    session.commit()
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", nargs="*", default=DEFAULT_SERIES)
    parser.add_argument("--period", type=int, default=60, choices=[1, 60, 1440])
    parser.add_argument("--max-markets", type=int, default=0, help="0 = no limit")
    parser.add_argument(
        "--include-zero-volume",
        action="store_true",
        help="also fetch candles for markets with zero lifetime volume (slow)",
    )
    parser.add_argument("--spot", action="store_true", help="also fetch daily spot klines")
    parser.add_argument("--report", action="store_true", help="coverage report only, no fetch")
    args = parser.parse_args()

    engine = get_engine()
    create_all_tables(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        if args.report:
            for s in args.series:
                print(coverage_report(session, s, args.period).summary())
            return

        with KalshiPublicClient(max_reads_per_second=8) as client:
            for s in args.series:
                markets, candles = fetch_series(
                    client,
                    session,
                    s,
                    period_minutes=args.period,
                    max_markets=args.max_markets,
                    skip_zero_volume=not args.include_zero_volume,
                )
                logger.info("{}: done — {} markets, {} new candles", s, markets, candles)
                print(coverage_report(session, s, args.period).summary())

        if args.spot:
            inserted = fetch_spot(session)
            logger.info("spot klines: {} new rows", inserted)


if __name__ == "__main__":
    main()
