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


@dataclass
class ValidationStatus:
    """What the operator needs to see about the current best validation
    evidence (kxbtc15m-validation-rebuild §6.1): instrument scope, data
    provenance/freshness, the fee/resolution config versions the run
    assumed, and the promotion verdict. All fields degrade to None/"—"
    when the underlying run has not populated them yet."""

    run_id: int | None
    strategy_name: str | None
    evidence_class: str | None  # "diagnostic" | "validation"
    instrument_scope: str  # e.g. "KXBTC15M only" or "—"
    data_start_ts: int | None
    data_end_ts: int | None
    fee_config_version: str | None
    resolution_config_version: str | None
    calibrator_version: str | None
    promotion_status: str  # "passed" | "failed" | "not_evaluated" | "—"
    promotion_reasons: list[str]
    provenance: dict | None


def latest_validation_status(session: Session) -> ValidationStatus:
    """Read the most recent `validation`-class run if one exists, else the
    most recent run of any class, and surface its promotion/provenance
    fields. Never raises — a fresh DB just yields an all-empty status."""
    run = session.execute(
        select(BacktestRun)
        .where(BacktestRun.evidence_class == "validation")
        .order_by(desc(BacktestRun.created_at))
        .limit(1)
    ).scalar_one_or_none()
    if run is None:
        run = latest_backtest_run(session)
    if run is None:
        return ValidationStatus(
            run_id=None, strategy_name=None, evidence_class=None,
            instrument_scope="—", data_start_ts=None, data_end_ts=None,
            fee_config_version=None, resolution_config_version=None,
            calibrator_version=None, promotion_status="—", promotion_reasons=[],
            provenance=None,
        )

    prov = run.provenance or {}
    metrics = run.metrics_test or {}
    promotion = metrics.get("promotion") if isinstance(metrics, dict) else None
    promo_status = "not_evaluated"
    promo_reasons: list[str] = []
    if isinstance(promotion, dict):
        promo_status = "passed" if promotion.get("passed") else "failed"
        promo_reasons = list(promotion.get("reasons", []))

    scope = "—"
    if isinstance(prov, dict):
        series = prov.get("series") or prov.get("series_filter")
        if series:
            scope = f"{series} only" if isinstance(series, str) else str(series)
    if scope == "—" and run.evidence_class == "validation":
        scope = "KXBTC15M only"  # validation runs are KXBTC15M-scoped by construction

    calibrator = None
    if isinstance(prov, dict):
        calibrator = prov.get("calibrator_version")

    return ValidationStatus(
        run_id=run.id,
        strategy_name=run.strategy_name,
        evidence_class=run.evidence_class,
        instrument_scope=scope,
        data_start_ts=run.data_start_ts,
        data_end_ts=run.data_end_ts,
        fee_config_version=run.fee_config_version,
        resolution_config_version=run.resolution_config_version,
        calibrator_version=calibrator,
        promotion_status=promo_status,
        promotion_reasons=promo_reasons,
        provenance=prov if isinstance(prov, dict) else None,
    )


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
