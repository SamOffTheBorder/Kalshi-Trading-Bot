"""Read-only queries backing the dashboard views (spec: operator-dashboard).

Everything here reads from tables that already exist and are already
populated by the backtest engine: `BacktestRun`, `SignalRecord`,
`SimulatedTrade`. There is no live-trading data yet — the authenticated
client, risk layer, and strategies that would populate live positions/
funding/liquidation views don't exist until tasks.md §4-§7 are built. Those
panels render as explicit placeholders (see routes.py) rather than faking
numbers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from kalshi_bot.data.kalshi.coverage import CoverageReport, coverage_report
from kalshi_bot.storage import BacktestRun, SignalRecord, SimulatedTrade

BTC_SERIES = ["KXBTC", "KXBTCD", "KXBTC15M"]

# coverage_report does two full table scans per series (no index on
# series_ticker+period_minutes) — over the archived 1-minute candle history
# that's tens of seconds per series, far too slow for a page load. Cache
# and refresh on a timer instead of computing it per-request.
COVERAGE_CACHE_TTL_S = 120.0
_coverage_cache: tuple[float, list[CoverageReport]] | None = None


@dataclass
class EquityPoint:
    ts: int
    equity_usd: float


def recent_backtest_runs(session: Session, limit: int = 20) -> list[BacktestRun]:
    return list(
        session.execute(
            select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(limit)
        ).scalars()
    )


def latest_backtest_run(session: Session) -> BacktestRun | None:
    return session.execute(
        select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(1)
    ).scalar_one_or_none()


def recent_signals(
    session: Session, backtest_run_id: int | None = None, limit: int = 50
) -> list[SignalRecord]:
    stmt = select(SignalRecord).order_by(desc(SignalRecord.evaluated_at_ts)).limit(limit)
    if backtest_run_id is not None:
        stmt = stmt.where(SignalRecord.backtest_run_id == backtest_run_id)
    return list(session.execute(stmt).scalars())


def trades_for_run(session: Session, backtest_run_id: int) -> list[SimulatedTrade]:
    return list(
        session.execute(
            select(SimulatedTrade)
            .where(SimulatedTrade.backtest_run_id == backtest_run_id)
            .order_by(SimulatedTrade.entry_ts)
        ).scalars()
    )


def equity_curve(
    session: Session, backtest_run_id: int, starting_cash_usd: float
) -> list[EquityPoint]:
    """Reconstruct a coarse equity curve from settled trades in entry order.

    Not a substitute for the engine's own per-bar equity tracking (which
    isn't persisted) — this is a post-hoc view good enough for a dashboard
    chart: cash after each trade settles, in the order trades were entered.
    """
    trades = trades_for_run(session, backtest_run_id)
    points = [EquityPoint(ts=0, equity_usd=starting_cash_usd)]
    running = starting_cash_usd
    for t in trades:
        if t.net_pnl_usd is None or t.exit_ts is None:
            continue
        running += t.net_pnl_usd
        points.append(EquityPoint(ts=t.exit_ts, equity_usd=running))
    return points


def cached_btc_coverage() -> list[CoverageReport] | None:
    """Last computed coverage snapshot, or None before the first warm-up completes.

    Never runs the underlying full-table-scan query itself — see the
    module-level note. A background thread (app.py) calls
    `refresh_coverage_cache` on a timer to keep this warm.
    """
    return _coverage_cache[1] if _coverage_cache is not None else None


def refresh_coverage_cache(session: Session, period_minutes: int = 1) -> None:
    global _coverage_cache
    reports = [coverage_report(session, series, period_minutes) for series in BTC_SERIES]
    _coverage_cache = (time.monotonic(), reports)
