"""Enforced paper-trading promotion gate."""

from __future__ import annotations

from dataclasses import dataclass, replace

from kalshi_bot.backtest.report import AggregateReport


@dataclass(frozen=True)
class PromotionPolicy:
    min_trades: int = 30
    min_folds: int = 3
    min_coverage: float = 0.01
    min_expectancy_usd: float = 0.0
    require_positive_ci: bool = True
    max_brier: float | None = 0.25
    require_validation_evidence: bool = True


def is_diagnostic_only(report: AggregateReport) -> bool:
    """A run is diagnostic-only whenever its manifest is not known to be
    source-native (brti-constituent-history §D6). `None` (no manifest
    provenance recorded at all) is treated the same as `"reconstructed"` --
    fail-closed, matching `data.manifests.classify_provenance`."""
    return report.manifest_provenance_class != "source_native"


@dataclass(frozen=True)
class PromotionDecision:
    passed: bool
    reasons: tuple[str, ...]
    diagnostic_only: bool = False
    """True whenever this decision can reject a strategy but SHALL NOT be
    presented as a satisfied promotion criterion, regardless of `passed`."""

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "reasons": list(self.reasons),
            "diagnostic_only": self.diagnostic_only,
        }


def evaluate_promotion(
    report: AggregateReport, policy: PromotionPolicy | None = None
) -> PromotionDecision:
    policy = policy or PromotionPolicy()
    diagnostic_only = is_diagnostic_only(report)
    reasons: list[str] = []
    if policy.require_validation_evidence and report.evidence_class != "validation":
        reasons.append("evidence_class is not validation")
    if report.n_trades < policy.min_trades:
        reasons.append(f"only {report.n_trades} trades; need {policy.min_trades}")
    if len(report.folds) < policy.min_folds:
        reasons.append(f"only {len(report.folds)} folds; need {policy.min_folds}")
    if report.coverage < policy.min_coverage:
        reasons.append(f"coverage {report.coverage:.4f} below {policy.min_coverage:.4f}")
    if report.expectancy_usd is None or report.expectancy_usd <= policy.min_expectancy_usd:
        reasons.append("net expectancy does not clear the policy threshold")
    if (
        policy.max_brier is not None
        and report.brier is not None
        and report.brier > policy.max_brier
    ):
        reasons.append(f"Brier score {report.brier:.4f} exceeds {policy.max_brier:.4f}")
    if policy.require_positive_ci:
        cis = [r.expectancy_ci for r in report.folds if r.expectancy_ci is not None]
        if not cis or any(low <= 0 for low, _ in cis):
            reasons.append("at least one fold lacks a positive day-blocked expectancy CI")
    for component in report.component_gates:
        if not component.passed:
            reasons.append(f"component_failed:{component.component_id}")
            if component.sample_count < component.min_samples:
                reasons.append(
                    f"component_failed:{component.component_id}:insufficient_samples"
                )
            if not component.data_ok:
                reasons.append(f"component_failed:{component.component_id}:data")
            if not component.economics_ok:
                reasons.append(f"component_failed:{component.component_id}:economics")
            if not component.risk_ok:
                reasons.append(f"component_failed:{component.component_id}:risk")
            reasons.extend(
                f"component_failed:{component.component_id}:{reason}"
                for reason in component.reasons
            )
    numerically_clears_bar = not reasons
    # Reconstructed data may reject a strategy, never admit one (D6): a
    # diagnostic-only run that clears every numeric bar still does not pass
    # -- it is reported separately as "requires captured-BRTI validation"
    # rather than as a satisfied promotion criterion. A diagnostic-only run
    # that fails stays a directly actionable rejection.
    passed = numerically_clears_bar and not diagnostic_only
    if diagnostic_only and numerically_clears_bar:
        reasons = [*reasons, "diagnostic_only_requires_captured_brti_validation"]
    return PromotionDecision(passed, tuple(reasons), diagnostic_only=diagnostic_only)


def enforce_paper_promotion(
    report: AggregateReport, policy: PromotionPolicy | None = None
) -> AggregateReport:
    decision = evaluate_promotion(report, policy)
    if decision.diagnostic_only and (
        "diagnostic_only_requires_captured_brti_validation" in decision.reasons
    ):
        status = "diagnostic_pending_validation"
    else:
        status = "passed" if decision.passed else "failed"
    return replace(report, promotion_status=status, promotion_reasons=decision.reasons)


__all__ = [
    "PromotionDecision",
    "PromotionPolicy",
    "enforce_paper_promotion",
    "evaluate_promotion",
]
