"""Deterministic validation for agent artifacts."""

from __future__ import annotations

from collections.abc import Iterable

from kalshi_bot.agents.contracts import (
    AgentVerdictArtifact,
    CouncilDecisionArtifact,
    EvidenceBundle,
)
from kalshi_bot.agents.profiles import RoleConfig


def validate_verdict_artifact(
    verdict: AgentVerdictArtifact,
    *,
    bundle: EvidenceBundle,
    role_config: RoleConfig,
) -> tuple[str, ...]:
    errors: list[str] = []
    if verdict.role != role_config.role:
        errors.append("role_mismatch")
    if verdict.evidence_bundle_hash != bundle.bundle_hash:
        errors.append("evidence_bundle_mismatch")
    evidence_ids = {item.evidence_id for item in bundle.items}
    for claim in (*verdict.claims, *verdict.counterevidence):
        unknown = set(claim.evidence_ids).difference(evidence_ids)
        if unknown:
            errors.append(f"unknown_evidence:{','.join(sorted(unknown))}")
    if (
        verdict.role in {"researcher", "rules_settlement", "portfolio_risk"}
        and verdict.proposed_action is not None
    ):
        errors.append("role_cannot_propose_action")
    if verdict.price_ceiling is not None and not role_config.allow_price_ceiling:
        errors.append("role_cannot_propose_price_ceiling")
    if verdict.size_ceiling is not None and not role_config.allow_size_ceiling:
        errors.append("role_cannot_propose_size_ceiling")
    if verdict.parse_status == "invalid":
        errors.append("invalid_parse_status")
    return tuple(dict.fromkeys(errors))


def validate_master_decision(
    decision: CouncilDecisionArtifact,
    *,
    verdict_ids: Iterable[str],
) -> tuple[str, ...]:
    errors: list[str] = []
    known = set(verdict_ids)
    supporting = set(decision.supporting_verdict_ids)
    dissenting = set(decision.dissenting_verdict_ids)
    if supporting.difference(known):
        errors.append("unknown_supporting_verdict")
    if dissenting.difference(known):
        errors.append("unknown_dissenting_verdict")
    if supporting.intersection(dissenting):
        errors.append("verdict_cannot_support_and_dissent")
    if decision.outcome == "take" and not decision.policy.can_synthesize:
        errors.append("policy_does_not_allow_take")
    return tuple(dict.fromkeys(errors))


def format_repair_payload(raw_output: str, errors: Iterable[str]) -> dict[str, object]:
    """Build a repair request that cannot add new evidence or analysis."""

    return {
        "original_output": raw_output,
        "schema_errors": list(dict.fromkeys(errors)),
        "instruction": "Return the same answer with schema formatting repaired only; add no facts.",
    }


__all__ = [
    "format_repair_payload",
    "validate_master_decision",
    "validate_verdict_artifact",
]
