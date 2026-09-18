"""Execution-realistic, research-only sports feasibility evaluation."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field


def time_to_event_bucket(minutes: float | None) -> str:
    if minutes is None or minutes < 0:
        return "unknown"
    if minutes <= 5:
        return "0-5m"
    if minutes <= 30:
        return "5-30m"
    if minutes <= 120:
        return "30-120m"
    if minutes <= 360:
        return "2-6h"
    if minutes <= 1_440:
        return "6-24h"
    return "24h+"


@dataclass(frozen=True)
class SportsObservation:
    market_ticker: str
    observed_at: int
    available_at: int
    close_ts: int
    market_probability: float
    candidate_probability: float
    outcome: int | None = None
    yes_ask_cents: int | None = None
    yes_bid_cents: int | None = None
    available_depth: float = 0.0
    fee_rate: float = 0.0
    quantity: float = 1.0

    @property
    def minutes_to_event(self) -> float:
        return max(0.0, (self.close_ts - self.observed_at) / 60)

    @property
    def tte_bucket(self) -> str:
        return time_to_event_bucket(self.minutes_to_event)


@dataclass(frozen=True)
class CandidateSignal:
    probability: float
    generated_at: int
    feature_available_at: int
    name: str = "candidate"

    def validate(self) -> None:
        if not 0 <= self.probability <= 1:
            raise ValueError("candidate probability must be in [0,1]")
        if self.feature_available_at > self.generated_at:
            raise ValueError("future feature leakage")


@dataclass(frozen=True)
class FillResult:
    eligible: bool
    side: str | None
    quantity: float
    price_cents: float | None
    fee_usd: float
    expected_net_pnl_usd: float | None
    rejection_reason: str | None = None


def simulate_fill(
    observation: SportsObservation,
    *,
    edge_threshold: float = 0.0,
    slippage_cents: float = 0.0,
    quantity: float | None = None,
) -> FillResult:
    """Simulate only a quoted/depth-backed entry; never fills from volume."""
    candidate = observation.candidate_probability
    market = observation.market_probability
    if candidate - market > edge_threshold:
        side, edge, quote = "yes", candidate - market, observation.yes_ask_cents
    elif market - candidate > edge_threshold:
        side, edge, quote = (
            "no",
            market - candidate,
            (100 - observation.yes_bid_cents) if observation.yes_bid_cents is not None else None,
        )
    else:
        return FillResult(False, None, 0.0, None, 0.0, None, "edge_below_threshold")
    if quote is None:
        return FillResult(False, side, 0.0, None, 0.0, None, "missing_quote")
    qty = min(
        float(quantity if quantity is not None else observation.quantity),
        observation.available_depth,
    )
    if qty <= 0:
        return FillResult(False, side, 0.0, None, 0.0, None, "insufficient_depth")
    price = float(quote) + slippage_cents
    if price >= 100:
        return FillResult(False, side, 0.0, None, 0.0, None, "slippage_exceeds_contract")
    fee = qty * (price / 100.0) * observation.fee_rate
    expected = qty * (edge - slippage_cents / 100.0) - fee
    return FillResult(True, side, qty, price, fee, expected)


def _brier(values: Sequence[tuple[float, int]]) -> float | None:
    return sum((p - y) ** 2 for p, y in values) / len(values) if values else None


def _log_loss(values: Sequence[tuple[float, int]]) -> float | None:
    if not values:
        return None
    return sum(
        -(
            y * math.log(min(max(p, 1e-12), 1 - 1e-12))
            + (1 - y) * math.log(min(max(1 - p, 1e-12), 1 - 1e-12))
        )
        for p, y in values
    ) / len(values)


def chronological_evaluation(
    observations: Iterable[SportsObservation],
    *,
    holdout_ts: int,
    min_train_samples: int = 30,
    calibrator: Callable[[Sequence[float], Sequence[int]], Callable[[float], float]] | None = None,
) -> dict:
    rows = sorted(observations, key=lambda row: row.observed_at)
    if any(row.available_at > row.observed_at for row in rows):
        # Availability after observation is normal; it cannot be used until
        # available_at, so only observations available by the decision are valid.
        rows = [row for row in rows if row.available_at <= row.observed_at]
    train = [r for r in rows if r.observed_at < holdout_ts]
    holdout = [r for r in rows if r.observed_at >= holdout_ts]
    if any(r.observed_at >= holdout_ts for r in train):
        raise ValueError("holdout contamination")
    if len(train) < min_train_samples:
        return {
            "valid": False,
            "reason": "insufficient_training_data",
            "train_count": len(train),
            "holdout_count": len(holdout),
        }
    fit = (
        calibrator(
            [r.candidate_probability for r in train],
            [r.outcome for r in train if r.outcome is not None],
        )
        if calibrator and all(r.outcome is not None for r in train)
        else (lambda p: p)
    )
    pairs_candidate = [
        (min(max(float(fit(r.candidate_probability)), 0), 1), int(r.outcome))
        for r in holdout
        if r.outcome is not None
    ]
    pairs_market = [
        (min(max(r.market_probability, 0), 1), int(r.outcome))
        for r in holdout
        if r.outcome is not None
    ]
    return {
        "valid": True,
        "train_count": len(train),
        "holdout_count": len(holdout),
        "candidate_brier": _brier(pairs_candidate),
        "market_brier": _brier(pairs_market),
        "candidate_log_loss": _log_loss(pairs_candidate),
        "market_log_loss": _log_loss(pairs_market),
        "by_tte": {
            bucket: {
                "count": sum(1 for r in holdout if r.tte_bucket == bucket),
                "candidate_brier": _brier(
                    [
                        (min(max(float(fit(r.candidate_probability)), 0), 1), int(r.outcome))
                        for r in holdout
                        if r.tte_bucket == bucket and r.outcome is not None
                    ]
                ),
            }
            for bucket in sorted({r.tte_bucket for r in holdout})
        },
    }


@dataclass
class FeasibilityReport:
    outcome: str
    sample_count: int
    opportunity_count: int
    eligible_fills: int
    rejected_fills: int
    net_pnl_usd: float
    max_drawdown_usd: float
    concentration: float
    evaluation: dict = field(default_factory=dict)
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    execution_enabled: bool = False
    candidate_kind: str = "market-baseline"
    feature_versions: tuple[str, ...] = ()
    evidence_hashes: tuple[str, ...] = ()
    model_metadata: dict = field(default_factory=dict)
    costs: dict = field(default_factory=dict)
    executable_fills: int = 0

    def as_dict(self) -> dict:
        return {**self.__dict__, "execution_enabled": False}


@dataclass(frozen=True)
class SportsAdmission:
    admitted: bool
    reason: str
    report_outcome: str
    operator_acknowledged: bool


def evaluate_sports_paper_admission(
    report: FeasibilityReport,
    *,
    rules_verified: bool,
    provider_evidence: bool,
    fresh_data: bool,
    liquid_quote: bool,
    strategy_version: str | None,
    operator_acknowledged: bool,
) -> SportsAdmission:
    if report.outcome != "research_promising":
        return SportsAdmission(
            False, "research_not_promising", report.outcome, operator_acknowledged
        )
    checks = (
        (rules_verified, "rules_unverified"),
        (provider_evidence, "provider_evidence_missing"),
        (fresh_data, "stale_data"),
        (liquid_quote, "no_fillable_quote"),
        (bool(strategy_version), "strategy_version_missing"),
        (operator_acknowledged, "operator_ack_required"),
    )
    for passed, reason in checks:
        if not passed:
            return SportsAdmission(False, reason, report.outcome, operator_acknowledged)
    return SportsAdmission(True, "pass", report.outcome, True)


def feasibility_report(
    observations: Iterable[SportsObservation],
    *,
    holdout_ts: int,
    min_sample_size: int = 100,
    min_confidence: float = 0.95,
    edge_threshold: float = 0.0,
    slippage_cents: float = 0.0,
    candidate_kind: str = "market-baseline",
    feature_versions: Iterable[str] = (),
    evidence_hashes: Iterable[str] = (),
    model_metadata: dict | None = None,
) -> FeasibilityReport:
    rows = list(observations)
    evaluation = chronological_evaluation(
        rows, holdout_ts=holdout_ts, min_train_samples=max(1, min_sample_size // 2)
    )
    if not evaluation.get("valid"):
        return FeasibilityReport(
            "insufficient_data",
            len(rows),
            0,
            0,
            0,
            0.0,
            0.0,
            0.0,
            evaluation,
            candidate_kind=candidate_kind,
            feature_versions=tuple(feature_versions),
            evidence_hashes=tuple(evidence_hashes),
            model_metadata=model_metadata or {},
            executable_fills=0,
        )
    holdout = [r for r in rows if r.observed_at >= holdout_ts]
    fills = [
        simulate_fill(r, edge_threshold=edge_threshold, slippage_cents=slippage_cents)
        for r in holdout
    ]
    eligible = [f for f in fills if f.eligible]
    pnl = sum(f.expected_net_pnl_usd or 0 for f in eligible)
    curve = []
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for f in eligible:
        running += f.expected_net_pnl_usd or 0
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)
        curve.append(running)
    counts: dict[str, int] = {}
    for f in fills:
        if f.rejection_reason:
            counts[f.rejection_reason] = counts.get(f.rejection_reason, 0) + 1
    concentration = max((abs(f.expected_net_pnl_usd or 0) for f in eligible), default=0.0) / max(
        abs(pnl), 1e-12
    )
    promising = (
        len(holdout) >= min_sample_size
        and len(eligible) > 0
        and pnl > 0
        and (evaluation.get("candidate_brier") or 1) < (evaluation.get("market_brier") or 0)
        and concentration < 0.5
    )
    # Confidence is intentionally a declared gate input; no execution side effect.
    outcome = (
        "research_promising"
        if promising and min_confidence >= 0.95
        else ("insufficient_data" if len(holdout) < min_sample_size else "park")
    )
    return FeasibilityReport(
        outcome,
        len(rows),
        sum(
            1
            for r in holdout
            if abs(r.candidate_probability - r.market_probability) > edge_threshold
        ),
        len(eligible),
        len(fills) - len(eligible),
        pnl,
        max_dd,
        concentration,
        evaluation,
        counts,
        candidate_kind=candidate_kind,
        feature_versions=tuple(feature_versions),
        evidence_hashes=tuple(evidence_hashes),
        model_metadata=model_metadata or {},
        costs={"slippage_cents": slippage_cents, "fee_rate_in_observations": True},
        executable_fills=len(eligible),
    )


def compare_candidate_variants(
    variants: dict[str, Iterable[SportsObservation]],
    *,
    holdout_ts: int,
    min_sample_size: int = 100,
    edge_threshold: float = 0.0,
    slippage_cents: float = 0.0,
    feature_versions: dict[str, Iterable[str]] | None = None,
    evidence_hashes: dict[str, Iterable[str]] | None = None,
    model_metadata: dict[str, dict] | None = None,
) -> dict[str, FeasibilityReport]:
    """Evaluate baseline/flow/evidence/combined on exactly the same holdout."""
    feature_versions = feature_versions or {}
    evidence_hashes = evidence_hashes or {}
    model_metadata = model_metadata or {}
    return {
        name: feasibility_report(
            rows,
            holdout_ts=holdout_ts,
            min_sample_size=min_sample_size,
            edge_threshold=edge_threshold,
            slippage_cents=slippage_cents,
            candidate_kind=name,
            feature_versions=feature_versions.get(name, ()),
            evidence_hashes=evidence_hashes.get(name, ()),
            model_metadata=model_metadata.get(name),
        )
        for name, rows in variants.items()
    }
