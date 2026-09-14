"""Read-only council lineage inspection for operators and the dashboard."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.storage.models import (
    AgentDefinitionSnapshotRecord,
    AgentVerdictRecord,
    CouncilDecisionRecord,
    CouncilRunRecord,
    EvidenceBundleRecord,
)


def council_run_details(session: Session, run_id: str) -> dict[str, object] | None:
    run = session.get(CouncilRunRecord, run_id)
    if run is None:
        return None
    evidence = list(
        session.execute(
            select(EvidenceBundleRecord)
            .where(EvidenceBundleRecord.council_run_id == run_id)
            .order_by(EvidenceBundleRecord.created_at, EvidenceBundleRecord.id)
        ).scalars()
    )
    definitions = list(
        session.execute(
            select(AgentDefinitionSnapshotRecord)
            .where(AgentDefinitionSnapshotRecord.council_run_id == run_id)
            .order_by(AgentDefinitionSnapshotRecord.role, AgentDefinitionSnapshotRecord.id)
        ).scalars()
    )
    verdicts = list(
        session.execute(
            select(AgentVerdictRecord)
            .where(AgentVerdictRecord.council_run_id == run_id)
            .order_by(AgentVerdictRecord.role, AgentVerdictRecord.attempt)
        ).scalars()
    )
    decisions = list(
        session.execute(
            select(CouncilDecisionRecord)
            .where(CouncilDecisionRecord.council_run_id == run_id)
            .order_by(CouncilDecisionRecord.created_at, CouncilDecisionRecord.id)
        ).scalars()
    )
    return {
        "run": {
            "id": run.id,
            "candidate_id": run.candidate_id,
            "domain": run.domain,
            "specialization_key": run.specialization_key,
            "instrument_id": run.instrument_id,
            "profile_id": run.profile_id,
            "profile_version": run.profile_version,
            "policy_version": run.policy_version,
            "candidate_hash": run.candidate_hash,
            "evidence_bundle_hash": run.evidence_bundle_hash,
            "decision_ts": run.decision_ts,
            "state": run.state,
            "created_at": run.created_at,
        },
        "evidence": [
            {
                "id": row.id,
                "bundle_hash": row.bundle_hash,
                "decision_ts": row.decision_ts,
                "bundle": row.bundle_json,
            }
            for row in evidence
        ],
        "agents": [
            {
                "id": row.id,
                "agent_id": row.agent_id,
                "role": row.role,
                "provider": row.provider,
                "model": row.model,
                "prompt_version": row.prompt_version,
                "schema_version": row.schema_version,
                "capability_hash": row.capability_hash,
                "permissions": row.permissions,
            }
            for row in definitions
        ],
        "verdicts": [
            {
                "id": row.id,
                "role": row.role,
                "attempt": row.attempt,
                "status": row.status,
                "verdict": row.verdict_json,
                "raw_output_hash": row.raw_output_hash,
                "usage": {
                    "input_tokens": row.input_tokens,
                    "output_tokens": row.output_tokens,
                    "cost_usd": row.cost_usd,
                    "latency_ms": row.latency_ms,
                },
                "a2a_task_id": row.a2a_task_id,
            }
            for row in verdicts
        ],
        "decisions": [
            {
                "id": row.id,
                "outcome": row.outcome,
                "final_status": row.final_status,
                "reason": row.reason,
                "policy": row.policy_json,
                "artifact": row.artifact_json,
            }
            for row in decisions
        ],
    }


__all__ = ["council_run_details"]
