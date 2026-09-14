"""Reproducible, asset-isolated underlying-market backtests.

This module is intentionally independent from the Kalshi binary broker.  It
turns causal external bars into a small, deterministic return series and
evaluates that series inside a frozen train/validation/holdout plan.  The
prediction-contract and perpetual paths can consume the resulting feature
metadata, but neither is allowed to substitute this return series for its own
instrument settlement or mark data.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field

from kalshi_bot.backtest.metrics import day_block_bootstrap_ci
from kalshi_bot.strategy.underlying_features import (
    UnderlyingBar,
    UnderlyingFeatures,
    build_underlying_features,
)


@dataclass(frozen=True)
class UnderlyingSignal:
    """A model output for one causal feature snapshot.

    ``expected_return`` is signed.  A zero value is a valid no-trade output.
    ``probability`` is optional and is scored only when the model explicitly
    supplies one; it is never inferred from an LLM or from the realized return.
    Evidence hashes are an allowlisted, captured-input boundary, not a place
    for a model to smuggle new web output into a backtest.
    """

    expected_return: float
    probability: float | None = None
    evidence_hashes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(self.expected_return):
            raise ValueError("expected_return must be finite")
        if self.probability is not None and not 0.0 <= self.probability <= 1.0:
            raise ValueError("probability must be between zero and one")


@dataclass(frozen=True)
class UnderlyingBacktestPlan:
    """Frozen experiment geometry and lineage for one asset/cadence."""

    asset_id: str
    cadence_minutes: int
    train_start_ts: int
    train_end_ts: int
    validation_start_ts: int
    validation_end_ts: int
    holdout_start_ts: int
    holdout_end_ts: int
    lookback_bars: int
    horizon_bars: int
    purge_seconds: int
    seed: int
    manifest_sha256: str
    feature_version: str
    model_version: str
    execution_config: dict[str, object] = field(default_factory=dict)
    allowlisted_evidence_hashes: tuple[str, ...] = ()
    holdout_evaluation_count: int = 0

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise ValueError("asset_id is required")
        if self.cadence_minutes <= 0 or self.lookback_bars < 1 or self.horizon_bars < 1:
            raise ValueError("cadence, lookback_bars, and horizon_bars must be positive")
        windows = (
            (self.train_start_ts, self.train_end_ts),
            (self.validation_start_ts, self.validation_end_ts),
            (self.holdout_start_ts, self.holdout_end_ts),
        )
        if any(start >= end for start, end in windows):
            raise ValueError("every backtest window must have positive duration")
        if not (
            self.train_end_ts + self.purge_seconds <= self.validation_start_ts
            and self.validation_end_ts + self.purge_seconds <= self.holdout_start_ts
        ):
            raise ValueError("validation and holdout windows violate the purge")
        minimum_purge = (self.lookback_bars + self.horizon_bars) * self.cadence_minutes * 60
        if self.purge_seconds < minimum_purge:
            raise ValueError("purge must cover maximum lookback plus prediction horizon")
        if self.holdout_evaluation_count < 0:
            raise ValueError("holdout_evaluation_count cannot be negative")

    @property
    def plan_hash(self) -> str:
        payload = asdict(self)
        payload["allowlisted_evidence_hashes"] = sorted(self.allowlisted_evidence_hashes)
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()

    def split_for(self, decision_ts: int) -> str | None:
        if self.train_start_ts <= decision_ts < self.train_end_ts:
            return "train"
        if self.validation_start_ts <= decision_ts < self.validation_end_ts:
            return "validation"
        if self.holdout_start_ts <= decision_ts < self.holdout_end_ts:
            return "holdout"
        return None


@dataclass(frozen=True)
class UnderlyingSample:
    asset_id: str
    cadence_minutes: int
    decision_ts: int
    available_at: int
    expected_return: float
    realized_return: float
    net_return: float
    baseline_net_return: float
    traded: bool
    probability: float | None = None
    evidence_hashes: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnderlyingSegmentMetrics:
    split: str
    asset_id: str
    cadence_minutes: int
    sample_count: int
    traded_count: int
    wins: int
    win_rate: float | None
    gross_return: float
    modeled_cost: float
    net_return: float
    baseline_net_return: float
    expectancy: float | None
    brier: float | None
    confidence_interval: tuple[float, float] | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class UnderlyingBacktestReport:
    plan_hash: str
    manifest_sha256: str
    asset_id: str
    cadence_minutes: int
    feature_version: str
    model_version: str
    seed: int
    samples: int
    rejected_uncaptured_evidence: int
    holdout_evaluations: int
    segments: tuple[UnderlyingSegmentMetrics, ...]

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["segments"] = [segment.as_dict() for segment in self.segments]
        return payload


SignalFn = Callable[[UnderlyingFeatures], UnderlyingSignal]


def build_underlying_samples(
    bars: Iterable[UnderlyingBar],
    plan: UnderlyingBacktestPlan,
    signal_fn: SignalFn,
    *,
    cost_bps: float = 0.0,
) -> tuple[tuple[UnderlyingSample, ...], int]:
    """Build samples using only bars causally available at each decision.

    Returns ``(samples, rejected_evidence_count)``.  A signal that references
    a hash not present in the frozen plan is excluded rather than allowed into
    training or holdout evaluation.
    """

    if cost_bps < 0:
        raise ValueError("cost_bps cannot be negative")
    rows = sorted(
        (
            bar
            for bar in bars
            if bar.asset_id == plan.asset_id and bar.cadence_minutes == plan.cadence_minutes
        ),
        key=lambda bar: bar.close_ts,
    )
    samples: list[UnderlyingSample] = []
    rejected = 0
    cost = cost_bps / 10_000.0
    for index in range(0, len(rows) - plan.horizon_bars):
        current = rows[index]
        future = rows[index + plan.horizon_bars]
        split = plan.split_for(current.close_ts)
        if split is None or future.close <= 0 or current.close <= 0:
            continue
        features = build_underlying_features(
            rows[: index + 1],
            asset_id=plan.asset_id,
            cadence_minutes=plan.cadence_minutes,
            decision_ts=current.close_ts,
            lookback_bars=plan.lookback_bars,
        )
        if not features.available:
            continue
        signal = signal_fn(features)
        if not set(signal.evidence_hashes) <= set(plan.allowlisted_evidence_hashes):
            rejected += 1
            continue
        realized = future.close / current.close - 1.0
        direction = 1 if signal.expected_return > 0 else -1 if signal.expected_return < 0 else 0
        gross = direction * realized if direction else 0.0
        baseline_direction = (
            1
            if (features.return_lookback or 0.0) > 0
            else -1
            if (features.return_lookback or 0.0) < 0
            else 0
        )
        baseline = baseline_direction * realized if baseline_direction else 0.0
        samples.append(
            UnderlyingSample(
                plan.asset_id,
                plan.cadence_minutes,
                current.close_ts,
                current.available_at,
                signal.expected_return,
                realized,
                gross - (cost if direction else 0.0),
                baseline - (cost if baseline_direction else 0.0),
                bool(direction),
                signal.probability,
                signal.evidence_hashes,
            )
        )
    return tuple(samples), rejected


def _brier(samples: Sequence[UnderlyingSample]) -> float | None:
    pairs = [
        (sample.probability, int(sample.realized_return > 0))
        for sample in samples
        if sample.probability is not None
    ]
    if not pairs:
        return None
    return sum((probability - outcome) ** 2 for probability, outcome in pairs) / len(pairs)


def _segment_metrics(
    split: str,
    samples: Sequence[UnderlyingSample],
    plan: UnderlyingBacktestPlan,
    *,
    cost_bps: float,
) -> UnderlyingSegmentMetrics:
    traded = [sample for sample in samples if sample.traded]
    wins = sum(1 for sample in traded if sample.net_return > 0)
    returns = [sample.net_return for sample in traded]
    modeled_cost = sum(cost_bps / 10_000.0 for sample in traded)
    return UnderlyingSegmentMetrics(
        split,
        plan.asset_id,
        plan.cadence_minutes,
        len(samples),
        len(traded),
        wins,
        wins / len(traded) if traded else None,
        sum(
            sample.realized_return
            * (1 if sample.expected_return > 0 else -1 if sample.expected_return < 0 else 0)
            for sample in traded
        ),
        modeled_cost,
        sum(returns),
        sum(sample.baseline_net_return for sample in samples),
        sum(returns) / len(returns) if returns else None,
        _brier(samples),
        day_block_bootstrap_ci([(sample.decision_ts, sample.net_return) for sample in traded]),
    )


def run_underlying_backtest(
    bars: Iterable[UnderlyingBar],
    plan: UnderlyingBacktestPlan,
    signal_fn: SignalFn,
    *,
    cost_bps: float = 0.0,
) -> UnderlyingBacktestReport:
    """Run one frozen, asset-isolated experiment.

    A holdout plan is single-use.  Reusing a plan after a holdout evaluation
    requires freezing a new plan/hash, which prevents silent post-holdout
    threshold tuning.
    """

    if plan.holdout_evaluation_count:
        raise ValueError("holdout already evaluated; freeze a new plan before rerunning")
    samples, rejected = build_underlying_samples(bars, plan, signal_fn, cost_bps=cost_bps)
    segments = tuple(
        _segment_metrics(
            split,
            tuple(sample for sample in samples if plan.split_for(sample.decision_ts) == split),
            plan,
            cost_bps=cost_bps,
        )
        for split in ("train", "validation", "holdout")
    )
    return UnderlyingBacktestReport(
        plan.plan_hash,
        plan.manifest_sha256,
        plan.asset_id,
        plan.cadence_minutes,
        plan.feature_version,
        plan.model_version,
        plan.seed,
        len(samples),
        rejected,
        1,
        segments,
    )


__all__ = [
    "UnderlyingBacktestPlan",
    "UnderlyingBacktestReport",
    "UnderlyingSample",
    "UnderlyingSegmentMetrics",
    "UnderlyingSignal",
    "build_underlying_samples",
    "run_underlying_backtest",
]
