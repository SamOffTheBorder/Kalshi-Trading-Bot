"""Stable, transport-neutral contracts for trading-agent collaboration."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AgentRole = Literal[
    "researcher",
    "bull_thesis",
    "bear_thesis",
    "skeptic",
    "execution_liquidity",
    "rules_settlement",
    "portfolio_risk",
    "master_synthesizer",
]
RoleCriticality = Literal["critical", "advisory", "non_voting"]
VerdictDecision = Literal["support", "oppose", "abstain", "block"]
VerdictSeverity = Literal["info", "warn", "block"]
CouncilOutcome = Literal["take", "hold", "reject"]
CouncilRunState = Literal[
    "created",
    "screened",
    "reviewing",
    "reconsidering",
    "synthesizing",
    "admitted",
    "completed",
    "failed",
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class TradeCandidateEnvelope(ContractModel):
    """A strategy-produced candidate; never an order or broker instruction."""

    candidate_id: str = Field(min_length=1)
    domain: Literal["prediction", "perp", "sports"]
    specialization_key: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    strategy_name: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    decision_ts: int = Field(gt=0)
    proposed_action: Literal["BUY_YES", "BUY_NO", "LONG", "SHORT"]
    proposed_price: float | None = Field(default=None, ge=0)
    proposed_size: float | None = Field(default=None, gt=0)
    horizon_seconds: int | None = Field(default=None, gt=0)
    settlement_rule_id: str | None = Field(default=None, min_length=1)
    evidence_manifest_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_domain_action(self) -> TradeCandidateEnvelope:
        if self.domain == "prediction" and self.proposed_action not in {"BUY_YES", "BUY_NO"}:
            raise ValueError("prediction candidates require BUY_YES or BUY_NO")
        if self.domain == "perp" and self.proposed_action not in {"LONG", "SHORT"}:
            raise ValueError("perp candidates require LONG or SHORT")
        if self.domain == "sports" and self.proposed_action not in {"BUY_YES", "BUY_NO"}:
            raise ValueError("sports candidates require BUY_YES or BUY_NO")
        return self


class EvidenceItem(ContractModel):
    evidence_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    observed_at: int = Field(gt=0)
    available_at: int = Field(gt=0)
    content_hash: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class EvidenceBundle(ContractModel):
    """Content-addressed as-of inputs shared by the first-round reviewers."""

    bundle_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    domain: Literal["prediction", "perp", "sports"]
    decision_ts: int = Field(gt=0)
    items: tuple[EvidenceItem, ...] = ()
    missing_fields: tuple[str, ...] = ()
    conflict_fields: tuple[str, ...] = ()
    excluded_items: tuple[str, ...] = ()
    bundle_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def _enforce_asof_cutoff(self) -> EvidenceBundle:
        late = [item.evidence_id for item in self.items if item.available_at > self.decision_ts]
        if late:
            raise ValueError(f"evidence is unavailable at decision_ts: {late}")
        ids = [item.evidence_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence IDs must be unique within a bundle")
        return self

    def computed_hash(self) -> str:
        payload = {
            "bundle_id": self.bundle_id,
            "candidate_id": self.candidate_id,
            "domain": self.domain,
            "decision_ts": self.decision_ts,
            "items": [item.model_dump(mode="json") for item in self.items],
            "missing_fields": list(self.missing_fields),
            "conflict_fields": list(self.conflict_fields),
            "excluded_items": list(self.excluded_items),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class EvidenceClaim(ContractModel):
    claim: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    strength: float = Field(ge=0, le=1)


class AgentUsage(ContractModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)


class AgentDefinitionSnapshot(ContractModel):
    agent_id: str = Field(min_length=1)
    role: AgentRole
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    capability_hash: str | None = Field(default=None, min_length=1)
    permissions: tuple[str, ...] = ()


class AgentVerdictArtifact(ContractModel):
    """Validated output from one role attempt."""

    verdict_id: str = Field(min_length=1)
    council_run_id: str = Field(min_length=1)
    role: AgentRole
    specialization_key: str = Field(min_length=1)
    evidence_bundle_hash: str = Field(min_length=1)
    agent_snapshot_id: str = Field(min_length=1)
    attempt: int = Field(default=1, ge=1)
    decision: VerdictDecision
    severity: VerdictSeverity
    confidence: float = Field(ge=0, le=1)
    claims: tuple[EvidenceClaim, ...] = ()
    counterevidence: tuple[EvidenceClaim, ...] = ()
    assumptions: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    falsifiers: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    proposed_action: str | None = Field(default=None, min_length=1)
    price_ceiling: float | None = Field(default=None, ge=0)
    size_ceiling: float | None = Field(default=None, gt=0)
    usage: AgentUsage = AgentUsage()
    raw_output_hash: str | None = Field(default=None, min_length=1)
    parse_status: Literal["valid", "repaired", "invalid"] = "valid"
    a2a_task_id: str | None = Field(default=None, min_length=1)


class CouncilPolicyResult(ContractModel):
    policy_version: str = Field(min_length=1)
    quorum_met: bool
    required_roles_complete: bool
    vetoes: tuple[str, ...] = ()
    abstentions: tuple[AgentRole, ...] = ()
    missing_roles: tuple[AgentRole, ...] = ()
    reason_codes: tuple[str, ...] = ()

    @property
    def can_synthesize(self) -> bool:
        return (
            self.quorum_met
            and self.required_roles_complete
            and not self.vetoes
            and not self.reason_codes
        )


class CouncilDecisionArtifact(ContractModel):
    """Master output; still only a recommendation until deterministic admission."""

    decision_id: str = Field(min_length=1)
    council_run_id: str = Field(min_length=1)
    outcome: CouncilOutcome
    selected_action: str | None = Field(default=None, min_length=1)
    max_entry_price: float | None = Field(default=None, ge=0)
    max_size: float | None = Field(default=None, gt=0)
    expires_at: int | None = Field(default=None, gt=0)
    invalidation_conditions: tuple[str, ...] = ()
    summary: str = Field(min_length=1)
    supporting_verdict_ids: tuple[str, ...] = ()
    dissenting_verdict_ids: tuple[str, ...] = ()
    policy: CouncilPolicyResult
    recommendation_only: Literal[True] = True

    @model_validator(mode="after")
    def _hold_cannot_size(self) -> CouncilDecisionArtifact:
        if self.outcome != "take" and (
            self.max_entry_price is not None or self.max_size is not None
        ):
            raise ValueError("only take decisions may contain executable ceilings")
        if self.outcome == "take" and not self.selected_action:
            raise ValueError("take decisions require selected_action")
        return self


__all__ = [
    "AgentDefinitionSnapshot",
    "AgentRole",
    "AgentUsage",
    "AgentVerdictArtifact",
    "CouncilDecisionArtifact",
    "CouncilOutcome",
    "CouncilPolicyResult",
    "CouncilRunState",
    "EvidenceBundle",
    "EvidenceClaim",
    "EvidenceItem",
    "RoleCriticality",
    "TradeCandidateEnvelope",
    "VerdictDecision",
    "VerdictSeverity",
]
