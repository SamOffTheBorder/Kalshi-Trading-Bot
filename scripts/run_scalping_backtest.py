"""Run trend_scalp or level_break over archived KXBTC15M-era history.

Train/test split is engine-enforced (design decision 6, tasks.md 8.3):
pin the split with --split-date and freeze config BEFORE looking at
anything at or after that date. Re-running against the test segment while
tuning defeats the whole point of a holdout — see tasks.md 8.3's note on
Phase 1's test window being peeked 4 times.

Usage:
  # tune on train only (split date is still required, but you should not
  # look at the printed test-segment numbers while iterating on config):
  uv run python scripts/run_scalping_backtest.py trend_scalp --split-date 2026-08-15

  # config overrides, JSON blob merged over the strategy's dataclass defaults:
  uv run python scripts/run_scalping_backtest.py trend_scalp \
      --split-date 2026-08-15 \
      --config '{"min_trend_zscore": 0.15, "min_touches": 1, "level_tolerance_pct": 0.006}'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from sqlalchemy import func, select  # noqa: E402

from kalshi_bot.backtest.engine import BacktestEngine  # noqa: E402
from kalshi_bot.config.settings import get_settings  # noqa: E402
from kalshi_bot.data.provenance import (  # noqa: E402
    ValidationRunConfig,
    dataset_fingerprint,
    git_commit,
)
from kalshi_bot.execution.backtest_broker import BacktestBroker  # noqa: E402
from kalshi_bot.risk.drawdown_guard import DrawdownGuard  # noqa: E402
from kalshi_bot.signals.fees import DEFAULT_FEE_CONFIG, DEFAULT_RESOLUTION_SPEC  # noqa: E402
from kalshi_bot.storage import (  # noqa: E402
    BacktestRun,
    Candle,
    create_all_tables,
    get_engine,
    get_session_factory,
)
from kalshi_bot.strategy.level_break import LevelBreakConfig, LevelBreakStrategy  # noqa: E402
from kalshi_bot.strategy.trend_scalp import TrendScalpConfig, TrendScalpStrategy  # noqa: E402

STRATEGIES = {
    "trend_scalp": (TrendScalpStrategy, TrendScalpConfig),
    "level_break": (LevelBreakStrategy, LevelBreakConfig),
}


def fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategy", choices=sorted(STRATEGIES))
    parser.add_argument(
        "--split-date",
        type=str,
        required=True,
        help="ISO date (UTC), e.g. 2026-08-15. Pin this BEFORE tuning and do not "
        "change it based on what the test segment shows (tasks.md 8.3).",
    )
    parser.add_argument(
        "--config", type=str, default=None, help="JSON overrides for the strategy config"
    )
    parser.add_argument("--cash", type=float, default=None)
    parser.add_argument("--eval-stride-s", type=int, default=900)
    parser.add_argument("--kxbtc15m-only", action="store_true",
                        help="restrict the dataset and stamp the run as validation evidence")
    parser.add_argument("--evidence-class", choices=["diagnostic", "validation"],
                        default="diagnostic")
    args = parser.parse_args()

    settings = get_settings()
    engine = get_engine(settings)
    create_all_tables(engine)
    session = get_session_factory(engine)()

    series_filter = "KXBTC15M" if args.kxbtc15m_only else None
    candle_window = select(func.min(Candle.end_period_ts), func.max(Candle.end_period_ts)).where(
        Candle.period_minutes == 1
    )
    if series_filter:
        candle_window = candle_window.where(Candle.series_ticker == series_filter)
    lo, hi = session.execute(candle_window).one()
    if lo is None:
        print("No archived candles. Run scripts/fetch_historical.py first.")
        return
    start_ts, end_ts = lo, hi

    split_ts = int(datetime.strptime(args.split_date, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())
    if not start_ts < split_ts < end_ts:
        print(f"--split-date {args.split_date} is outside the data window; aborting.")
        return

    cash = args.cash if args.cash is not None else settings.bankroll_total_usd
    evidence_class = "validation" if args.kxbtc15m_only else args.evidence_class

    strategy_cls, config_cls = STRATEGIES[args.strategy]
    config = config_cls()
    if args.config:
        overrides = json.loads(args.config)
        config = replace(config, **overrides)
    strategy = strategy_cls(config)

    guard = DrawdownGuard(
        pause_pct=settings.max_drawdown_pause_pct,
        halt_pct=settings.max_drawdown_halt_pct,
        initial_equity=cash,
        peak_window_s=int(settings.drawdown_peak_window_days * 86_400),
        # Backtest-only (tasks.md 8.3 finding, 2026-09-06): see docstring
        # above the module-level constant note in drawdown_guard.py. NEVER
        # set this on a live path.
        allow_reentry_after_halt=True,
    )
    bt = BacktestEngine(
        strategy=strategy,
        broker=BacktestBroker(starting_cash_usd=cash),
        session=session,
        starting_cash_usd=cash,
        kelly_fraction=settings.kelly_fraction,
        max_position_pct=settings.max_position_pct,
        guard=guard,
        candle_period_minutes=1,
        eval_stride_s=args.eval_stride_s,
    )

    print(f"strategy={args.strategy} config={config}")
    print(f"Backtesting {fmt(start_ts)} .. {fmt(end_ts)} (split {fmt(split_ts)}), ${cash:.2f}")
    result = await bt.run(start_ts=start_ts, end_ts=end_ts, split_ts=split_ts)
    run = session.get(BacktestRun, result.run_id)
    if run is not None:
        run.evidence_class = evidence_class
        run.fee_config_version = DEFAULT_FEE_CONFIG.version
        run.resolution_config_version = DEFAULT_RESOLUTION_SPEC.version
        run.provenance = {
            **dataset_fingerprint(session, start_ts, end_ts, series_filter),
            "series_filter": series_filter or "ALL",
            "git_commit": git_commit(),
            "fee_config": DEFAULT_FEE_CONFIG.as_dict(),
            "resolution_spec": DEFAULT_RESOLUTION_SPEC.as_dict(),
            "validation_config": ValidationRunConfig().as_dict() if series_filter else None,
        }
        session.commit()
    print()
    print(result.summary())
    print(f"ever_halted={guard.ever_halted} final_guard_state={guard.state}")


if __name__ == "__main__":
    asyncio.run(main())
