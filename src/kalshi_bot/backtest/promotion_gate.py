"""Enforced paper-trading promotion gate."""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class PromotionDecision:
    passed: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "reasons": list(self.reasons)}


def evaluate_promotion(
    report: AggregateReport, policy: PromotionPolicy | None = None
) -> PromotionDecision:
    policy = policy or PromotionPolicy()
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
    return PromotionDecision(not reasons, tuple(reasons))


def enforce_paper_promotion(
    report: AggregateReport, policy: PromotionPolicy | None = None
) -> AggregateReport:
    decision = evaluate_promotion(report, policy)
    return AggregateReport(**{**report.to_dict(), "folds": report.folds,
                              "promotion_status": "passed" if decision.passed else "failed"})


__all__ = [
    "PromotionDecision",
    "PromotionPolicy",
    "enforce_paper_promotion",
    "evaluate_promotion",
]
