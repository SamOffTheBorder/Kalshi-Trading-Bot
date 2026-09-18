"""Outcome-blind replay, baseline comparison, and promotion metrics."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from kalshi_bot.agents.contracts import CouncilOutcome, EvidenceBundle, TradeCandidateEnvelope
from kalshi_bot.agents.coordinator import CouncilRunResult


@dataclass(frozen=True)
class ReplaySample:
    sample_id: str
    candidate: TradeCandidateEnvelope
    evidence: EvidenceBundle
    realized_return_usd: float
    outcome: bool | None = None


@dataclass(frozen=True)
class ReplayObservation:
    sample_id: str
    council_outcome: CouncilOutcome
    baseline_outcome: CouncilOutcome
    single_agent_outcome: CouncilOutcome
    realized_return_usd: float
    council_valid: bool
    timed_out: bool
    citations_valid: bool
    probability: float | None = None
    realized_binary: int | None = None
    latency_ms: int = 0
    model_cost_usd: float = 0.0
    component: str = "default"


class OutcomeBlindReplayRunner:
    """Evaluate frozen inputs, then join outcomes after decisions are sealed."""

    def run(
        self,
        samples: Sequence[ReplaySample],
        *,
        council_fn: Callable[[TradeCandidateEnvelope, EvidenceBundle], CouncilRunResult],
        baseline_fn: Callable[[TradeCandidateEnvelope, EvidenceBundle], CouncilOutcome],
        single_agent_fn: Callable[[TradeCandidateEnvelope, EvidenceBundle], CouncilOutcome],
    ) -> tuple[ReplayObservation, ...]:
        observations: list[ReplayObservation] = []
        for sample in samples:
            # No outcome or future state is passed to any decision function.
            council = council_fn(sample.candidate, sample.evidence)
            baseline = baseline_fn(sample.candidate, sample.evidence)
            single = single_agent_fn(sample.candidate, sample.evidence)
            observations.append(
                ReplayObservation(
                    sample_id=sample.sample_id,
                    council_outcome=council.decision.outcome,
                    baseline_outcome=baseline,
                    single_agent_outcome=single,
                    realized_return_usd=sample.realized_return_usd,
                    council_valid=all(
                        attempt.verdict is not None
                        and attempt.verdict.parse_status != "invalid"
                        for attempt in council.attempts
                        if attempt.role != "master_synthesizer"
                    ),
                    timed_out=any(attempt.status == "timeout" for attempt in council.attempts),
                    citations_valid=all(
                        not attempt.errors for attempt in council.attempts if attempt.verdict
                    ),
                    latency_ms=max(
                        (attempt.verdict.usage.latency_ms or 0)
                        for attempt in council.attempts
                        if attempt.verdict
                    )
                    if any(attempt.verdict for attempt in council.attempts)
                    else 0,
                    model_cost_usd=council.cost_usd,
                    component=sample.candidate.specialization_key,
                )
            )
        return tuple(observations)


@dataclass(frozen=True)
class EvaluationMetrics:
    sample_count: int
    artifact_validity: float
    timeout_rate: float
    abstention_hold_rate: float
    citation_validity: float
    calibration_brier: float | None
    false_approvals: int
    false_vetoes: int
    net_result_after_costs: float
    drawdown: float
    disagreement_error_correlation: float
    decision_stability: float
    incremental_value: float
    latency_ms: float
    model_cost_usd: float

    def as_dict(self) -> dict[str, object]:
        return {
            "sample_count": self.sample_count,
            "artifact_validity": self.artifact_validity,
            "timeout_rate": self.timeout_rate,
            "abstention_hold_rate": self.abstention_hold_rate,
            "citation_validity": self.citation_validity,
            "calibration_brier": self.calibration_brier,
            "false_approvals": self.false_approvals,
            "false_vetoes": self.false_vetoes,
            "net_result_after_costs": self.net_result_after_costs,
            "drawdown": self.drawdown,
            "disagreement_error_correlation": self.disagreement_error_correlation,
            "decision_stability": self.decision_stability,
            "incremental_value": self.incremental_value,
            "latency_ms": self.latency_ms,
            "model_cost_usd": self.model_cost_usd,
        }


def compute_metrics(observations: Sequence[ReplayObservation]) -> EvaluationMetrics:
    n = len(observations)
    if n == 0:
        return EvaluationMetrics(
            0,
            0.0,
            0.0,
            0.0,
            0.0,
            None,
            0,
            0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        )
    returns = [observation.realized_return_usd for observation in observations]
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    errors = [observation.realized_return_usd <= 0 for observation in observations]
    disagreements = [
        observation.council_outcome != observation.single_agent_outcome
        for observation in observations
    ]
    correlation = _binary_correlation(disagreements, errors)
    brier_pairs = [
        (observation.probability, observation.realized_binary)
        for observation in observations
        if observation.probability is not None and observation.realized_binary is not None
    ]
    brier = (
        sum((probability - outcome) ** 2 for probability, outcome in brier_pairs)
        / len(brier_pairs)
        if brier_pairs
        else None
    )
    baseline_net = sum(
        observation.realized_return_usd
        for observation in observations
        if observation.baseline_outcome == "take"
    )
    net = sum(
        observation.realized_return_usd
        for observation in observations
        if observation.council_outcome == "take"
    ) - sum(observation.model_cost_usd for observation in observations)
    return EvaluationMetrics(
        sample_count=n,
        artifact_validity=sum(observation.council_valid for observation in observations) / n,
        timeout_rate=sum(observation.timed_out for observation in observations) / n,
        abstention_hold_rate=sum(
            observation.council_outcome == "hold" for observation in observations
        )
        / n,
        citation_validity=sum(observation.citations_valid for observation in observations) / n,
        calibration_brier=brier,
        false_approvals=sum(
            observation.council_outcome == "take" and observation.realized_return_usd <= 0
            for observation in observations
        ),
        false_vetoes=sum(
            observation.council_outcome != "take" and observation.realized_return_usd > 0
            for observation in observations
        ),
        net_result_after_costs=net,
        drawdown=drawdown,
        disagreement_error_correlation=correlation,
        decision_stability=sum(
            observation.council_outcome == observation.single_agent_outcome
            for observation in observations
        )
        / n,
        incremental_value=net - baseline_net,
        latency_ms=sum(observation.latency_ms for observation in observations) / n,
        model_cost_usd=sum(observation.model_cost_usd for observation in observations),
    )


def _binary_correlation(left: Sequence[bool], right: Sequence[bool]) -> float:
    if len(left) < 2 or len(set(left)) < 2 or len(set(right)) < 2:
        return 0.0
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=True))
    denominator_left = sum((a - left_mean) ** 2 for a in left) ** 0.5
    denominator_right = sum((b - right_mean) ** 2 for b in right) ** 0.5
    return numerator / (denominator_left * denominator_right)


@dataclass(frozen=True)
class FrozenEvaluationPlan:
    profile_id: str
    profile_version: str
    evaluation_window: str
    sample_minimum: int
    thresholds: Mapping[str, float]
    evidence_manifest_hash: str
    policy_version: str
    prompt_hash: str
    model_assignments: Mapping[str, str]
    code_revision: str
    random_seed: int
    registered_at: int

    @property
    def plan_hash(self) -> str:
        body = json.dumps(self.__dict__, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(body.encode()).hexdigest()


def freeze_evaluation_plan(
    *,
    profile_id: str,
    profile_version: str,
    evaluation_window: str,
    sample_minimum: int,
    thresholds: Mapping[str, float],
    evidence_manifest_hash: str,
    policy_version: str,
    prompt_hash: str,
    model_assignments: Mapping[str, str],
    code_revision: str,
    random_seed: int,
    registered_at: int,
) -> FrozenEvaluationPlan:
    if sample_minimum <= 0 or not evaluation_window or not evidence_manifest_hash:
        raise ValueError("evaluation plan is incomplete")
    if not thresholds or not model_assignments or not code_revision:
        raise ValueError("evaluation plan must freeze thresholds, models, and code")
    return FrozenEvaluationPlan(
        profile_id,
        profile_version,
        evaluation_window,
        sample_minimum,
        dict(thresholds),
        evidence_manifest_hash,
        policy_version,
        prompt_hash,
        dict(model_assignments),
        code_revision,
        random_seed,
        registered_at,
    )


@dataclass(frozen=True)
class EvaluationReport:
    plan: FrozenEvaluationPlan
    heldout_completed_at: int
    metrics: EvaluationMetrics
    component_metrics: Mapping[str, EvaluationMetrics] = field(default_factory=dict)


@dataclass(frozen=True)
class VariantComparison:
    champion: EvaluationMetrics
    challenger: EvaluationMetrics
    shared_error_correlation: float
    challenger_incremental_value: float


def compare_variants(
    champion_observations: Sequence[ReplayObservation],
    challenger_observations: Sequence[ReplayObservation],
) -> VariantComparison:
    """Compare economical/strong or same/cross-provider variants fairly."""

    if len(champion_observations) != len(challenger_observations):
        raise ValueError("variant comparisons require the identical sample set")
    champion = compute_metrics(champion_observations)
    challenger = compute_metrics(challenger_observations)
    champion_errors = [
        item.council_outcome == "take" and item.realized_return_usd <= 0
        for item in champion_observations
    ]
    challenger_errors = [
        item.council_outcome == "take" and item.realized_return_usd <= 0
        for item in challenger_observations
    ]
    return VariantComparison(
        champion=champion,
        challenger=challenger,
        shared_error_correlation=_binary_correlation(champion_errors, challenger_errors),
        challenger_incremental_value=challenger.net_result_after_costs
        - champion.net_result_after_costs,
    )


def evaluate_promotion(report: EvaluationReport) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    metrics = report.metrics
    if report.plan.registered_at >= report.heldout_completed_at:
        reasons.append("threshold_registration_after_or_at_heldout_evaluation")
    if metrics.sample_count < report.plan.sample_minimum:
        reasons.append("insufficient_samples")
    thresholds = report.plan.thresholds
    if metrics.incremental_value <= thresholds.get("min_incremental_value", 0.0):
        reasons.append("non_positive_net_incremental_value")
    if metrics.timeout_rate > thresholds.get("max_timeout_rate", 1.0):
        reasons.append("timeout_threshold")
    if metrics.false_approvals > thresholds.get("max_false_approvals", float("inf")):
        reasons.append("false_approval_threshold")
    if metrics.calibration_brier is not None and metrics.calibration_brier > thresholds.get(
        "max_brier", float("inf")
    ):
        reasons.append("calibration_threshold")
    if not report.component_metrics:
        reasons.append("missing_component_metrics")
    for component, component_metric in report.component_metrics.items():
        if component_metric.false_approvals > thresholds.get("max_false_approvals", float("inf")):
            reasons.append(f"component_failure:{component}")
    return not reasons, tuple(reasons)


__all__ = [
    "EvaluationMetrics",
    "EvaluationReport",
    "FrozenEvaluationPlan",
    "OutcomeBlindReplayRunner",
    "ReplayObservation",
    "ReplaySample",
    "VariantComparison",
    "compare_variants",
    "compute_metrics",
    "evaluate_promotion",
    "freeze_evaluation_plan",
]
