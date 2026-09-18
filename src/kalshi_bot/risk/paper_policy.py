"""Versioned cross-domain paper risk policy and deterministic admission."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskPolicy:
    version: str = "2026-09-paper-v1"
    max_global_exposure_usd: float = 100.0
    max_domain_exposure_usd: float = 60.0
    max_asset_exposure_usd: float = 40.0
    max_correlation_group_exposure_usd: float = 80.0
    max_market_exposure_usd: float = 25.0
    max_drawdown_pct: float = 0.10
    max_daily_loss_usd: float = 30.0
    max_consecutive_losses: int = 3
    max_data_age_seconds: int = 120
    require_reconciled: bool = True


@dataclass(frozen=True)
class RiskRequest:
    domain: str
    asset_id: str
    correlation_group: str
    market_id: str
    worst_case_loss_usd: float
    data_age_seconds: int
    reconciled: bool
    global_exposure_usd: float = 0.0
    domain_exposure_usd: float = 0.0
    asset_exposure_usd: float = 0.0
    group_exposure_usd: float = 0.0
    market_exposure_usd: float = 0.0
    drawdown_pct: float = 0.0
    daily_loss_usd: float = 0.0
    consecutive_losses: int = 0


@dataclass(frozen=True)
class RiskVerdict:
    allowed: bool
    reason: str | None
    policy_version: str


DEFAULT_RISK_POLICY = RiskPolicy()


def admit_risk(request: RiskRequest, policy: RiskPolicy = DEFAULT_RISK_POLICY) -> RiskVerdict:
    if request.worst_case_loss_usd <= 0:
        return RiskVerdict(False, "invalid_worst_case_loss", policy.version)
    if policy.require_reconciled and not request.reconciled:
        return RiskVerdict(False, "reconciliation_required", policy.version)
    if request.data_age_seconds > policy.max_data_age_seconds:
        return RiskVerdict(False, "stale_required_data", policy.version)
    if request.drawdown_pct >= policy.max_drawdown_pct:
        return RiskVerdict(False, "drawdown_limit", policy.version)
    if request.daily_loss_usd >= policy.max_daily_loss_usd:
        return RiskVerdict(False, "daily_loss_limit", policy.version)
    if request.consecutive_losses >= policy.max_consecutive_losses:
        return RiskVerdict(False, "consecutive_loss_limit", policy.version)
    scopes = (
        ("global_budget", request.global_exposure_usd, policy.max_global_exposure_usd),
        ("domain_budget", request.domain_exposure_usd, policy.max_domain_exposure_usd),
        ("asset_budget", request.asset_exposure_usd, policy.max_asset_exposure_usd),
        (
            "correlation_group_budget",
            request.group_exposure_usd,
            policy.max_correlation_group_exposure_usd,
        ),
        ("market_budget", request.market_exposure_usd, policy.max_market_exposure_usd),
    )
    for name, used, limit in scopes:
        if used + request.worst_case_loss_usd > limit:
            return RiskVerdict(False, name, policy.version)
    return RiskVerdict(True, None, policy.version)


__all__ = ["DEFAULT_RISK_POLICY", "RiskPolicy", "RiskRequest", "RiskVerdict", "admit_risk"]
