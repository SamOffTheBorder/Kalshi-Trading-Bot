"""Append-only persistence helpers for council lineage."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy.orm import Session

from kalshi_bot.agents.contracts import (
    AgentDefinitionSnapshot,
    AgentVerdictArtifact,
    CouncilDecisionArtifact,
    EvidenceBundle,
    TradeCandidateEnvelope,
)
from kalshi_bot.agents.profiles import CouncilProfile
from kalshi_bot.storage.models import (
    AgentDefinitionSnapshotRecord,
    AgentVerdictRecord,
    CouncilDecisionRecord,
    CouncilRunRecord,
    EvidenceBundleRecord,
)

_SECRET_KEY = re.compile(
    r"(?:token|secret|password|private[_-]?key|credential|authorization)", re.I
)


def _hash_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def redact_payload(value: Any) -> Any:
    """Recursively remove credential-shaped fields before audit persistence."""

    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_payload(item) for item in value]
    return value


def redact_raw_output(raw_output: str | None, *, max_chars: int = 20_000) -> str | None:
    if raw_output is None:
        return None
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        return raw_output[:max_chars]
    encoded = json.dumps(redact_payload(parsed), sort_keys=True, separators=(",", ":"))
    return encoded[:max_chars]


def raw_output_hash(raw_output: str | None) -> str | None:
    if raw_output is None:
        return None
    return hashlib.sha256(raw_output.encode()).hexdigest()


def append_council_run(
    session: Session,
    *,
    run_id: str,
    candidate: TradeCandidateEnvelope,
    profile: CouncilProfile,
    evidence: EvidenceBundle,
    policy_version: str,
    created_at: int,
    paper_run_id: str | None = None,
) -> CouncilRunRecord:
    row = CouncilRunRecord(
        id=run_id,
        paper_run_id=paper_run_id,
        candidate_id=candidate.candidate_id,
        domain=candidate.domain,
        specialization_key=candidate.specialization_key,
        instrument_id=candidate.instrument_id,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        policy_version=policy_version,
        candidate_hash=_hash_json(candidate.model_dump(mode="json")),
        evidence_bundle_hash=evidence.bundle_hash,
        decision_ts=candidate.decision_ts,
        state="created",
        candidate_json=redact_payload(candidate.model_dump(mode="json")),
        created_at=created_at,
    )
    session.add(row)
    session.flush()
    return row


def append_evidence_bundle(
    session: Session,
    *,
    council_run_id: str,
    evidence: EvidenceBundle,
    created_at: int,
) -> EvidenceBundleRecord:
    row = EvidenceBundleRecord(
        id=evidence.bundle_id,
        council_run_id=council_run_id,
        candidate_id=evidence.candidate_id,
        decision_ts=evidence.decision_ts,
        bundle_hash=evidence.bundle_hash,
        bundle_json=redact_payload(evidence.model_dump(mode="json")),
        created_at=created_at,
    )
    session.add(row)
    session.flush()
    return row


def append_agent_definition(
    session: Session,
    *,
    council_run_id: str,
    snapshot_id: str,
    snapshot: AgentDefinitionSnapshot,
    created_at: int,
) -> AgentDefinitionSnapshotRecord:
    row = AgentDefinitionSnapshotRecord(
        id=snapshot_id,
        council_run_id=council_run_id,
        agent_id=snapshot.agent_id,
        role=snapshot.role,
        provider=snapshot.provider,
        model=snapshot.model,
        prompt_version=snapshot.prompt_version,
        schema_version=snapshot.schema_version,
        capability_hash=snapshot.capability_hash,
        permissions=list(snapshot.permissions),
        created_at=created_at,
    )
    session.add(row)
    session.flush()
    return row


def append_verdict(
    session: Session,
    *,
    verdict: AgentVerdictArtifact,
    request_hash: str,
    raw_output: str | None,
    status: str,
    created_at: int,
) -> AgentVerdictRecord:
    usage = verdict.usage
    row = AgentVerdictRecord(
        id=verdict.verdict_id,
        council_run_id=verdict.council_run_id,
        evidence_bundle_hash=verdict.evidence_bundle_hash,
        role=verdict.role,
        attempt=verdict.attempt,
        request_hash=request_hash,
        status=status,
        verdict_json=redact_payload(verdict.model_dump(mode="json")),
        raw_output_hash=raw_output_hash(raw_output),
        raw_output_redacted=redact_raw_output(raw_output),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=usage.cost_usd,
        latency_ms=usage.latency_ms,
        a2a_task_id=verdict.a2a_task_id,
        created_at=created_at,
    )
    session.add(row)
    session.flush()
    return row


def append_decision(
    session: Session,
    *,
    decision: CouncilDecisionArtifact,
    final_status: str,
    reason: str | None,
    created_at: int,
) -> CouncilDecisionRecord:
    row = CouncilDecisionRecord(
        id=decision.decision_id,
        council_run_id=decision.council_run_id,
        outcome=decision.outcome,
        final_status=final_status,
        reason=reason,
        policy_json=redact_payload(decision.policy.model_dump(mode="json")),
        artifact_json=redact_payload(decision.model_dump(mode="json")),
        created_at=created_at,
    )
    session.add(row)
    session.flush()
    return row


__all__ = [
    "append_agent_definition",
    "append_council_run",
    "append_decision",
    "append_evidence_bundle",
    "append_verdict",
    "raw_output_hash",
    "redact_payload",
    "redact_raw_output",
]
