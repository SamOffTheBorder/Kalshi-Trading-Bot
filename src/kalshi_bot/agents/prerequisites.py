"""Deterministic prerequisites for future perp and sports council profiles."""

from __future__ import annotations

from dataclasses import dataclass

from kalshi_bot.agents.profiles import CouncilProfile, resolve_profile


@dataclass(frozen=True)
class PerpPrerequisites:
    real_directional_strategy: bool
    fresh_mark: bool
    realized_funding: bool
    discovery_eligible: bool
    admission_passed: bool

    @property
    def eligible(self) -> bool:
        return all(self.__dict__.values())


@dataclass(frozen=True)
class SportsPrerequisites:
    feasibility_report_id: str | None
    feasibility_status: str
    verified_rules: bool
    fresh_provider_evidence: bool
    liquid_observations: bool
    operator_acknowledged: bool

    @property
    def eligible(self) -> bool:
        return (
            bool(self.feasibility_report_id)
            and self.feasibility_status == "research_promising"
            and self.verified_rules
            and self.fresh_provider_evidence
            and self.liquid_observations
            and self.operator_acknowledged
        )


def require_perp_profile(
    specialization_key: str, prerequisites: PerpPrerequisites
) -> CouncilProfile:
    if not prerequisites.eligible:
        raise ValueError("perp prerequisites are not satisfied")
    profile = resolve_profile(specialization_key)
    if profile is None or profile.domain != "perp":
        raise ValueError(f"no perp council profile for {specialization_key}")
    return profile


def require_sports_profile(
    specialization_key: str, prerequisites: SportsPrerequisites
) -> CouncilProfile:
    if not prerequisites.eligible:
        raise ValueError("sports feasibility prerequisites are not satisfied")
    profile = resolve_profile(specialization_key)
    if profile is None or profile.domain != "sports":
        raise ValueError(f"no sports council profile for {specialization_key}")
    return profile


__all__ = [
    "PerpPrerequisites",
    "SportsPrerequisites",
    "require_perp_profile",
    "require_sports_profile",
]
