"""Promotion-oriented fold and aggregate reporting."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from kalshi_bot.backtest.metrics import brier_score, day_block_bootstrap_ci
from kalshi_bot.execution.backtest_broker import Settlement


@dataclass(frozen=True)
class FoldReport:
    fold_index: int
    n_trades: int
    expectancy_usd: float | None
    net_pnl_usd: float
    coverage: float
    brier: float | None
    modeled_cost_usd: float
    realized_cost_usd: float
    fills: int
    cancels: int
    partial_fills: int
    adverse_selection_usd: float | None
    expectancy_ci: tuple[float, float] | None
    parameter_stability: dict[str, float] | None = None
    latency_outage: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AggregateReport:
    evidence_class: str
    folds: tuple[FoldReport, ...]
    n_trades: int
    net_pnl_usd: float
    expectancy_usd: float | None
    coverage: float
    brier: float | None
    realized_cost_usd: float
    modeled_cost_usd: float
    fills: int
    cancels: int
    partial_fills: int
    promotion_status: str = "not_evaluated"
    promotion_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parameter_stability(values: dict[str, Sequence[float]]) -> dict[str, float]:
    """Summarize fold-to-fold parameter stability as mean, spread and range."""
    result: dict[str, float] = {}
    for name, samples in values.items():
        if not samples:
            continue
        mean = sum(samples) / len(samples)
        result[f"{name}.mean"] = mean
        result[f"{name}.min"] = min(samples)
        result[f"{name}.max"] = max(samples)
        result[f"{name}.range"] = max(samples) - min(samples)
    return result


def latency_outage_sensitivity(
    baseline_returns: Sequence[float], outage_returns: dict[str, Sequence[float]]
) -> dict[str, float]:
    """Compare mean expectancy under named latency/data-outage scenarios."""
    baseline = sum(baseline_returns) / len(baseline_returns) if baseline_returns else 0.0
    result = {"baseline_expectancy_usd": baseline}
    for name, values in outage_returns.items():
        mean = sum(values) / len(values) if values else 0.0
        result[f"{name}.expectancy_usd"] = mean
        result[f"{name}.drop_usd"] = baseline - mean
    return result


def build_fold_report(
    fold_index: int, settlements: list[Settlement], *, candidate_count: int | None = None,
    probabilities: list[float] | None = None, outcomes: list[bool | int] | None = None,
    modeled_cost_usd: float | None = None, fills: int | None = None,
    cancels: int = 0, partial_fills: int = 0,
    adverse_selection_usd: float | None = None, parameter_stability: dict[str, float] | None = None,
    latency_outage: dict[str, float] | None = None,
) -> FoldReport:
    n = len(settlements)
    net = sum(s.net_pnl_usd for s in settlements)
    realized = sum(s.fee_usd for s in settlements)
    probabilities = probabilities or []
    outcomes = outcomes or []
    expectancy = net / n if n else None
    coverage = n / candidate_count if candidate_count else (1.0 if n else 0.0)
    return FoldReport(
        fold_index, n, expectancy, net, coverage,
        brier_score(probabilities, outcomes) if probabilities else None,
        realized if modeled_cost_usd is None else modeled_cost_usd, realized,
        n if fills is None else fills, cancels, partial_fills, adverse_selection_usd,
        day_block_bootstrap_ci([(s.entry_ts, s.net_pnl_usd) for s in settlements]),
        parameter_stability, latency_outage,
    )


def aggregate_reports(
    reports: list[FoldReport], *, evidence_class: str = "validation"
) -> AggregateReport:
    trades = sum(r.n_trades for r in reports)
    net = sum(r.net_pnl_usd for r in reports)
    return AggregateReport(
        evidence_class=evidence_class, folds=tuple(reports), n_trades=trades,
        net_pnl_usd=net, expectancy_usd=net / trades if trades else None,
        coverage=sum(r.coverage for r in reports) / len(reports) if reports else 0.0,
        brier=_weighted_mean([(r.brier, r.n_trades) for r in reports]),
        realized_cost_usd=sum(r.realized_cost_usd for r in reports),
        modeled_cost_usd=sum(r.modeled_cost_usd for r in reports),
        fills=sum(r.fills for r in reports), cancels=sum(r.cancels for r in reports),
        partial_fills=sum(r.partial_fills for r in reports),
    )


def _weighted_mean(values: list[tuple[float | None, int]]) -> float | None:
    usable = [(v, n) for v, n in values if v is not None and n > 0]
    return sum(v * n for v, n in usable) / sum(n for _, n in usable) if usable else None


__all__ = [
    "AggregateReport",
    "FoldReport",
    "aggregate_reports",
    "build_fold_report",
    "latency_outage_sensitivity",
    "parameter_stability",
]
