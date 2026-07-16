"""Run the crypto mispricing strategy over the archived history.

The train/test split is required (engine-enforced). Default: last 25% of the
window is the test segment.

Usage:
  uv run python scripts/run_backtest.py                 # full archived window
  uv run python scripts/run_backtest.py --days 14       # most recent 14 days
  uv run python scripts/run_backtest.py --test-frac 0.3
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from sqlalchemy import func, select  # noqa: E402

from kalshi_bot.backtest.engine import BacktestEngine  # noqa: E402
from kalshi_bot.config.settings import get_settings  # noqa: E402
from kalshi_bot.execution.backtest_broker import BacktestBroker  # noqa: E402
from kalshi_bot.risk.drawdown_guard import DrawdownGuard  # noqa: E402
from kalshi_bot.risk.entry_throttle import EntryThrottle  # noqa: E402
from kalshi_bot.storage import (  # noqa: E402
    Candle,
    create_all_tables,
    get_engine,
    get_session_factory,
)
from kalshi_bot.strategy.crypto_mispricing import (  # noqa: E402
    CryptoMispricingConfig,
    CryptoMispricingStrategy,
)


def fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=0, help="restrict to most recent N days")
    parser.add_argument("--test-frac", type=float, default=0.25)
    parser.add_argument("--cash", type=float, default=None, help="default: Kalshi bankroll share")
    parser.add_argument("--fill-mode", choices=["pessimistic", "midpoint"], default="pessimistic")
    args = parser.parse_args()

    settings = get_settings()
    engine = get_engine(settings)
    create_all_tables(engine)
    session = get_session_factory(engine)()

    lo, hi = session.execute(
        select(func.min(Candle.end_period_ts), func.max(Candle.end_period_ts)).where(
            Candle.period_minutes == 1
        )
    ).one()
    if lo is None:
        print("No archived candles. Run scripts/fetch_historical.py first.")
        return
    start_ts = max(lo, hi - args.days * 86_400) if args.days else lo
    end_ts = hi
    if end_ts - start_ts < 4 * 3600:
        print(f"Window too thin ({fmt(start_ts)}..{fmt(end_ts)}); archive more history first.")
        return
    split_ts = int(end_ts - (end_ts - start_ts) * args.test_frac)

    cash = args.cash
    if cash is None:
        cash = settings.bankroll_total_usd * settings.bankroll_split_kalshi_pct

    strategy = CryptoMispricingStrategy(
        CryptoMispricingConfig(
            min_edge=settings.min_edge,
            max_model_divergence=settings.max_model_divergence,
            min_entry_probability=settings.min_entry_probability,
            max_entry_probability=settings.max_entry_probability,
            min_minutes_to_expiry=settings.min_minutes_to_expiry,
            mc_seed=1337,  # deterministic runs are comparable runs
        )
    )
    bt = BacktestEngine(
        strategy=strategy,
        broker=BacktestBroker(starting_cash_usd=cash, fill_mode=args.fill_mode),
        session=session,
        starting_cash_usd=cash,
        kelly_fraction=settings.kelly_fraction,
        max_position_pct=settings.max_position_pct,
        guard=DrawdownGuard(
            pause_pct=settings.max_drawdown_pause_pct,
            halt_pct=settings.max_drawdown_halt_pct,
            initial_equity=cash,
        ),
        throttle=EntryThrottle(
            max_entries=settings.max_entries_per_series_window,
            window_s=int(settings.entry_throttle_window_hours * 3600),
        ),
        candle_period_minutes=1,  # hourly markets are only tradeable at 1-min bars
    )

    print(f"Backtesting {fmt(start_ts)} .. {fmt(end_ts)} (split {fmt(split_ts)}), ${cash:.2f}")
    result = await bt.run(start_ts=start_ts, end_ts=end_ts, split_ts=split_ts)
    print()
    print(result.summary())


if __name__ == "__main__":
    asyncio.run(main())
