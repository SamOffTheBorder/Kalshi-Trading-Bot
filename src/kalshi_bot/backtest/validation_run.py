"""KXBTC15M walk-forward validation run (kxbtc15m-validation-rebuild §4.6).

Ties the causal `BacktestEngine`, the settlement-aware strategies (§4.2-4.4),
`rolling_folds` / `run_walkforward` (§3.3), fixed-risk sizing (§3.1), prior-
fold-only isotonic calibration (§4.3), and the enforced promotion gate (§3.6)
into one reproducible verdict per strategy arm.

Design points, all from the change's decisions:

- **Fresh per-fold state.** `run_walkforward` calls the evaluator factory once
  per fold; the factory here builds a new engine, broker, drawdown guard and
  throttle every time. Nothing carries across folds except the calibration
  sample, which is *supposed* to accumulate.
- **Calibration on prior folds only.** Before running fold *k* the evaluator
  fits an `IsotonicCalibrator` on the (raw P(YES), realized YES outcome) pairs
  collected from folds 0..k-1. Fold 0 runs on the identity calibrator. The
  isotonic fit is monotone, so it only corrects the level, never the ranking.
- **Calibration sample = the traded subset.** raw_p is recorded only for
  evaluations that produced a BUY, matching the subset the Brier check in the
  gate scores. Widening it to every in-window evaluation is a later
  refinement (it needs the strategy to emit `model_meta` on the
  `edge_below_threshold` HOLD too).
- **Fixed-risk sizing.** The engine runs with `sizing_mode="fixed_risk"`; a
  hold-to-settlement binary has no contract stop, so the sizer treats the
  whole premium as the risk (see `BacktestEngine.__init__`).
- **The window is the fold, not the whole archive.** Each fold runs the engine
  over `[train_start, test_end]` with `split_ts = test_start`; only the test
  segment's settlements feed that fold's report.

The module is storage-shaped but not CLI-shaped: `run_validation_arms` takes a
session factory and returns a plain dict, so it is unit-testable against a
synthetic in-memory archive. `scripts/run_validation.py` is the thin CLI.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kalshi_bot.backtest.engine import BacktestEngine
from kalshi_bot.backtest.promotion_gate import PromotionPolicy, evaluate_promotion
from kalshi_bot.backtest.report import (
    AggregateReport,
    FoldReport,
    aggregate_reports,
    build_fold_report,
)
from kalshi_bot.backtest.walkforward import WalkForwardFold, rolling_folds, run_walkforward
from kalshi_bot.execution.backtest_broker import BacktestBroker, Settlement
from kalshi_bot.risk.drawdown_guard import DrawdownGuard
from kalshi_bot.risk.fixed_risk import FixedRiskConfig
from kalshi_bot.storage.models import BRTIObservation, Candle, KalshiMarket
from kalshi_bot.strategy.base import Action, Decision, StrategyContext, StrategyProtocol
from kalshi_bot.strategy.settlement_prob import (
    Calibrator,
    IdentityCalibrator,
    IsotonicCalibrator,
    SettlementProbStrategy,
)
from kalshi_bot.strategy.short_horizon_trend import (
    TrendConditionedConfig,
    TrendConditionedSettlementStrategy,
)
from kalshi_bot.strategy.underlying_features import UnderlyingFeatures

SERIES = "KXBTC15M"
DEFAULT_STARTING_CASH_USD = 1_000.0

# Fold geometry. Deliberately few, fat folds: the gate's per-fold positive-CI
# requirement is easier to satisfy with more trades per fold, and the first
# meaningful verdict wants 3 folds, not 6 thin ones. These defaults match
# SCRATCHPAD/capture-window-sizing.md's conservative layout (28d train / 1d
# embargo / 14d test folds → ~71-day minimum contiguous window for 3 folds).
DEFAULT_TRAIN_SECONDS = 28 * 86_400
DEFAULT_TEST_SECONDS = 14 * 86_400
DEFAULT_EMBARGO_SECONDS = 86_400


@dataclass(frozen=True)
class ArmSpec:
    """One strategy arm of the validation run."""

    name: str
    build: Callable[[Calibrator], StrategyProtocol]


def _settlement_arm(calibrator: Calibrator) -> StrategyProtocol:
    return SettlementProbStrategy(calibrator=calibrator)


def _trend_drift_arm(calibrator: Calibrator) -> StrategyProtocol:
    return TrendConditionedSettlementStrategy(
        TrendConditionedConfig(use_trend_drift=True), calibrator=calibrator
    )


def _trend_control_arm(calibrator: Calibrator) -> StrategyProtocol:
    # use_trend_drift=False is exactly the settlement-aware baseline; it is the
    # control the trend arm's incremental value is measured against.
    return TrendConditionedSettlementStrategy(
        TrendConditionedConfig(use_trend_drift=False), calibrator=calibrator
    )


ARMS: tuple[ArmSpec, ...] = (
    ArmSpec("settlement_probability", _settlement_arm),
    ArmSpec("trend_drift", _trend_drift_arm),
    ArmSpec("trend_control", _trend_control_arm),
)


class _RecordingStrategy:
    """Delegates to a real strategy and records (market_ticker, raw P(YES))
    for every BUY it returns, so the calibration sample for the next fold can
    be built without re-parsing the persisted signal JSON."""

    def __init__(self, inner: StrategyProtocol) -> None:
        self._inner = inner
        self.name = inner.name
        self.raw_yes_by_market: dict[str, float] = {}

    def evaluate(self, context: StrategyContext) -> Decision:
        decision = self._inner.evaluate(context)
        if decision.action in (Action.BUY_YES, Action.BUY_NO):
            raw = decision.model_meta.get("raw_probability")
            if isinstance(raw, (int, float)):
                self.raw_yes_by_market[context.market_ticker] = float(raw)
        return decision


def _data_bounds(session: Session) -> tuple[int, int] | None:
    """(min close_ts, max close_ts) over settled KXBTC15M markets, or None
    when the archive has no usable KXBTC15M markets."""
    row = session.execute(
        select(func.min(KalshiMarket.close_ts), func.max(KalshiMarket.close_ts)).where(
            KalshiMarket.series_ticker == SERIES,
            KalshiMarket.result.is_not(None),
            KalshiMarket.result != "",
        )
    ).one()
    lo, hi = row
    if lo is None or hi is None or lo >= hi:
        return None
    return int(lo), int(hi)


def dataset_counts(session: Session) -> dict[str, int]:
    markets = session.scalar(
        select(func.count()).select_from(KalshiMarket).where(
            KalshiMarket.series_ticker == SERIES
        )
    ) or 0
    candles = session.scalar(
        select(func.count()).select_from(Candle).where(Candle.series_ticker == SERIES)
    ) or 0
    brti = session.scalar(select(func.count()).select_from(BRTIObservation)) or 0
    return {"markets": int(markets), "candles": int(candles), "brti": int(brti)}


def _candidate_count(session: Session, fold: WalkForwardFold) -> int:
    """KXBTC15M markets closing in the fold's test window — the denominator
    for the fold's coverage (trades / candidates)."""
    return int(
        session.scalar(
            select(func.count()).select_from(KalshiMarket).where(
                KalshiMarket.series_ticker == SERIES,
                KalshiMarket.result.is_not(None),
                KalshiMarket.result != "",
                KalshiMarket.close_ts > fold.test_start_ts,
                KalshiMarket.close_ts <= fold.test_end_ts,
            )
        )
        or 0
    )


def _run_one_fold(
    *,
    session_factory: Callable[[], Session],
    fold: WalkForwardFold,
    build: Callable[[Calibrator], StrategyProtocol],
    calibrator: Calibrator,
    candidate_count: int,
    fixed_risk_config: FixedRiskConfig,
    starting_cash_usd: float,
    underlying_features: tuple[UnderlyingFeatures, ...],
    require_source_alignment: bool,
) -> tuple[FoldReport, dict[str, float]]:
    """Run one walk-forward fold with fresh engine/broker/guard state and
    return its report plus this fold's {market_ticker: raw P(YES)} for the
    next fold's calibration set."""
    with session_factory() as session:
        recorder = _RecordingStrategy(build(calibrator))
        broker = BacktestBroker(starting_cash_usd=starting_cash_usd)
        # Fresh guard per fold (§3.3). Wide thresholds: the validation gate,
        # not the guard, is the promotion authority here — the guard only
        # exists so a fold that blows up mid-window stops trading rather than
        # compounding losses into a meaningless report.
        engine = BacktestEngine(
            strategy=recorder,
            broker=broker,
            session=session,
            starting_cash_usd=starting_cash_usd,
            kelly_fraction=1.0,  # unused: fixed-risk mode
            max_position_pct=fixed_risk_config.max_position_pct,
            guard=DrawdownGuard(
                pause_pct=0.25, halt_pct=0.40, initial_equity=starting_cash_usd
            ),
            throttle=None,
            candle_period_minutes=1,
            sizing_mode="fixed_risk",
            fixed_risk_config=fixed_risk_config,
            underlying_features=underlying_features,
            require_source_alignment=require_source_alignment,
        )
        asyncio.run(
            engine.run(
                start_ts=fold.train_start_ts,
                end_ts=fold.test_end_ts,
                split_ts=fold.test_start_ts,
            )
        )

        # Test-segment settlements only: entered at or after the fold's test
        # start. The engine keys settlements by market_ticker; a KXBTC15M
        # market's entry_ts is the fill timestep, always < its close_ts.
        test_settlements: list[Settlement] = [
            s for s in broker.settlements if s.entry_ts >= fold.test_start_ts
        ]

        # raw P(YES) recorded at decision time, paired with the realized YES
        # outcome for every traded market in this fold's test segment.
        results = _market_results(session, [s.market_ticker for s in test_settlements])
        probs: list[float] = []
        outcomes: list[bool] = []
        fold_raw_yes: dict[str, float] = {}
        for s in test_settlements:
            raw = recorder.raw_yes_by_market.get(s.market_ticker)
            won_yes = results.get(s.market_ticker)
            if raw is None or won_yes is None:
                continue
            probs.append(raw)
            outcomes.append(won_yes)
            fold_raw_yes[s.market_ticker] = raw

    report = build_fold_report(
        fold.index,
        test_settlements,
        candidate_count=candidate_count or None,
        probabilities=probs or None,
        outcomes=[bool(o) for o in outcomes] or None,
    )
    return report, fold_raw_yes


def _market_results(session: Session, tickers: Sequence[str]) -> dict[str, bool]:
    """{ticker: True if YES resolved} for the given tickers."""
    if not tickers:
        return {}
    rows = session.execute(
        select(KalshiMarket.ticker, KalshiMarket.result).where(
            KalshiMarket.ticker.in_(list(tickers))
        )
    ).all()
    return {t: (r or "").lower() == "yes" for t, r in rows}


def run_arm(
    *,
    session_factory: Callable[[], Session],
    build: Callable[[Calibrator], StrategyProtocol],
    folds: Sequence[WalkForwardFold],
    fixed_risk_config: FixedRiskConfig,
    starting_cash_usd: float,
    policy: PromotionPolicy,
    underlying_features: tuple[UnderlyingFeatures, ...] = (),
    require_source_alignment: bool = False,
) -> dict[str, object]:
    """Walk-forward one strategy arm across all folds and gate the aggregate.

    Calibration accumulates across folds: fold k is calibrated on the raw/
    outcome pairs from folds 0..k-1 only.
    """
    calib_pairs: list[tuple[float, float]] = []
    calib_results_cache: dict[str, bool] = {}

    def evaluator_factory(fold: WalkForwardFold) -> Callable[[WalkForwardFold], FoldReport]:
        # Fit the calibrator on everything seen in prior folds. Below 10
        # points IsotonicCalibrator.fit returns an IdentityCalibrator, so
        # early folds are effectively uncalibrated — intended.
        calibrator: Calibrator = (
            IsotonicCalibrator.fit(calib_pairs, version=f"fold{fold.index}-isotonic")
            if calib_pairs
            else IdentityCalibrator(version="fold0-identity")
        )
        with session_factory() as s:
            candidate_count = _candidate_count(s, fold)

        def _run(f: WalkForwardFold) -> FoldReport:
            report, fold_raw_yes = _run_one_fold(
                session_factory=session_factory,
                fold=f,
                build=build,
                calibrator=calibrator,
                candidate_count=candidate_count,
                fixed_risk_config=fixed_risk_config,
                starting_cash_usd=starting_cash_usd,
                underlying_features=underlying_features,
                require_source_alignment=require_source_alignment,
            )
            # Roll this fold's pairs into the calibration set for later folds.
            with session_factory() as s:
                for ticker, won in _market_results(s, list(fold_raw_yes)).items():
                    calib_results_cache[ticker] = won
            for ticker, raw in fold_raw_yes.items():
                calib_pairs.append((raw, 1.0 if calib_results_cache.get(ticker) else 0.0))
            return report

        return _run

    result = run_walkforward(folds, evaluator_factory)
    reports = [r for r in result.reports if isinstance(r, FoldReport)]
    aggregate = aggregate_reports(reports, evidence_class="validation")
    decision = evaluate_promotion(aggregate, policy)
    payload = aggregate.to_dict()
    payload["promotion_status"] = "passed" if decision.passed else "failed"
    payload["promotion_reasons"] = list(decision.reasons)
    return payload


def run_validation_arms(
    session_factory: Callable[[], Session],
    *,
    train_seconds: int = DEFAULT_TRAIN_SECONDS,
    test_seconds: int = DEFAULT_TEST_SECONDS,
    embargo_seconds: int = DEFAULT_EMBARGO_SECONDS,
    starting_cash_usd: float = DEFAULT_STARTING_CASH_USD,
    fixed_risk_config: FixedRiskConfig | None = None,
    policy: PromotionPolicy | None = None,
    underlying_features: tuple[UnderlyingFeatures, ...] = (),
    require_source_alignment: bool = False,
) -> dict[str, object]:
    """Run every arm and assemble the reproducible KXBTC15M verdict.

    Fail-closed: an archive without settled KXBTC15M markets, contract
    candles, or BRTI observations returns a NO-GO with an explicit
    data-availability reason and never substitutes another series.
    """
    fixed_risk_config = fixed_risk_config or FixedRiskConfig()
    policy = policy or PromotionPolicy()

    with session_factory() as session:
        counts = dataset_counts(session)
        bounds = _data_bounds(session)

    if not counts["markets"] or not counts["candles"] or not counts["brti"] or bounds is None:
        reason = (
            "NO-GO: archived KXBTC15M validation data is incomplete "
            f"(markets={counts['markets']}, candles={counts['candles']}, "
            f"brti={counts['brti']}); run scripts/fetch_historical.py and a "
            "deliberate BRTI capture/import first"
        )
        return {
            "instrument": SERIES,
            "evidence_class": "validation",
            "dataset": counts,
            "arms": {a.name: _empty_arm_payload(reason) for a in ARMS},
            "verdict": "FAIL",
            "reason": reason,
        }

    start_ts, end_ts = bounds
    folds = rolling_folds(
        start_ts=start_ts,
        end_ts=end_ts,
        train_seconds=train_seconds,
        test_seconds=test_seconds,
        embargo_seconds=embargo_seconds,
    )
    if len(folds) < policy.min_folds:
        reason = (
            f"NO-GO: {len(folds)} walk-forward fold(s) fit the archived window "
            f"[{start_ts}, {end_ts}]; the gate needs {policy.min_folds}. Capture "
            "more days (see SCRATCHPAD/capture-window-sizing.md)."
        )
        return {
            "instrument": SERIES,
            "evidence_class": "validation",
            "dataset": counts,
            "window": {"start_ts": start_ts, "end_ts": end_ts, "folds": len(folds)},
            "arms": {a.name: _empty_arm_payload(reason) for a in ARMS},
            "verdict": "FAIL",
            "reason": reason,
        }

    arms = {
        a.name: run_arm(
            session_factory=session_factory,
            build=a.build,
            folds=folds,
            fixed_risk_config=fixed_risk_config,
            starting_cash_usd=starting_cash_usd,
            policy=policy,
            underlying_features=underlying_features,
            require_source_alignment=require_source_alignment,
        )
        for a in ARMS
    }
    incremental = _incremental_trend_value(arms)
    any_pass = any(arm.get("promotion_status") == "passed" for arm in arms.values())
    return {
        "instrument": SERIES,
        "evidence_class": "validation",
        "dataset": counts,
        "window": {
            "start_ts": start_ts,
            "end_ts": end_ts,
            "folds": len(folds),
            "train_seconds": train_seconds,
            "test_seconds": test_seconds,
            "embargo_seconds": embargo_seconds,
        },
        "fee_config_version": fixed_risk_config.version,
        "arms": arms,
        "incremental_trend_vs_control": incremental,
        "verdict": "PASS" if any_pass else "FAIL",
    }


def _incremental_trend_value(arms: dict[str, dict[str, object]]) -> dict[str, object] | None:
    """Trend arm's out-of-sample net PnL minus its control's — the trend
    features are only interesting for what they add after costs, never for
    direction alone (§4.4)."""
    drift = arms.get("trend_drift")
    control = arms.get("trend_control")
    if not drift or not control:
        return None
    d_pnl = drift.get("net_pnl_usd")
    c_pnl = control.get("net_pnl_usd")
    if not isinstance(d_pnl, (int, float)) or not isinstance(c_pnl, (int, float)):
        return None
    return {
        "trend_net_pnl_usd": float(d_pnl),
        "control_net_pnl_usd": float(c_pnl),
        "incremental_net_pnl_usd": float(d_pnl) - float(c_pnl),
    }


def _empty_arm_payload(reason: str) -> dict[str, object]:
    aggregate: AggregateReport = aggregate_reports([], evidence_class="validation")
    payload = aggregate.to_dict()
    payload["promotion_status"] = "failed"
    payload["promotion_reasons"] = [reason]
    return payload


__all__ = [
    "ARMS",
    "DEFAULT_EMBARGO_SECONDS",
    "DEFAULT_TEST_SECONDS",
    "DEFAULT_TRAIN_SECONDS",
    "ArmSpec",
    "dataset_counts",
    "run_arm",
    "run_validation_arms",
]
