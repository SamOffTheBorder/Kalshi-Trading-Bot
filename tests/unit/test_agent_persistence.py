from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from kalshi_bot.agents.contracts import (
    AgentDefinitionSnapshot,
    AgentUsage,
    AgentVerdictArtifact,
    CouncilDecisionArtifact,
    CouncilPolicyResult,
    EvidenceBundle,
    EvidenceItem,
    TradeCandidateEnvelope,
)
from kalshi_bot.agents.persistence import (
    append_agent_definition,
    append_council_run,
    append_decision,
    append_evidence_bundle,
    append_verdict,
    redact_payload,
)
from kalshi_bot.agents.profiles import DEFAULT_COUNCIL_PROFILES
from kalshi_bot.storage import (
    AgentVerdictRecord,
    CouncilDecisionRecord,
    CouncilRunRecord,
    EvidenceBundleRecord,
    PaperAuditEvent,
    PaperRun,
    create_all_tables,
)


def _candidate() -> TradeCandidateEnvelope:
    return TradeCandidateEnvelope(
        candidate_id="candidate-1",
        domain="prediction",
        specialization_key="prediction/BTC/15m",
        instrument_id="KXBTC15M",
        strategy_name="test",
        strategy_version="1",
        decision_ts=1_700_000_000,
        proposed_action="BUY_YES",
        proposed_price=50,
        proposed_size=1,
        evidence_manifest_hash="manifest",
    )


def _evidence() -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id="bundle-1",
        candidate_id="candidate-1",
        domain="prediction",
        decision_ts=1_700_000_000,
        items=(
            EvidenceItem(
                evidence_id="quote-1",
                source="fixture",
                kind="quote",
                observed_at=1_699_999_999,
                available_at=1_699_999_999,
                content_hash="quote-hash",
                claim="quote exists",
            ),
        ),
        bundle_hash="bundle-hash",
    )


def test_council_lineage_is_additive_and_redacts_secrets():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    profile = DEFAULT_COUNCIL_PROFILES[0]
    candidate = _candidate()
    evidence = _evidence()
    policy = CouncilPolicyResult(
        policy_version="1",
        quorum_met=True,
        required_roles_complete=True,
    )
    with Session(engine) as session:
        run = append_council_run(
            session,
            run_id="run-1",
            candidate=candidate,
            profile=profile,
            evidence=evidence,
            policy_version="1",
            created_at=1,
        )
        append_evidence_bundle(session, council_run_id=run.id, evidence=evidence, created_at=1)
        append_agent_definition(
            session,
            council_run_id=run.id,
            snapshot_id="agent-1",
            snapshot=AgentDefinitionSnapshot(
                agent_id="agent-1",
                role="skeptic",
                provider="ollama",
                model="qwen3:14b",
                prompt_version="1",
                schema_version="1",
                permissions=("read_evidence",),
            ),
            created_at=1,
        )
        verdict = AgentVerdictArtifact(
            verdict_id="verdict-1",
            council_run_id=run.id,
            role="skeptic",
            specialization_key=candidate.specialization_key,
            evidence_bundle_hash=evidence.bundle_hash,
            agent_snapshot_id="agent-1",
            decision="abstain",
            severity="warn",
            confidence=0.5,
            usage=AgentUsage(input_tokens=2, output_tokens=3),
        )
        append_verdict(
            session,
            verdict=verdict,
            request_hash="request-1",
            raw_output='{"api_token":"secret","ok":true}',
            status="valid",
            created_at=1,
        )
        decision = CouncilDecisionArtifact(
            decision_id="decision-1",
            council_run_id=run.id,
            outcome="hold",
            summary="insufficient evidence",
            policy=policy,
        )
        append_decision(
            session,
            decision=decision,
            final_status="blocked",
            reason="insufficient_evidence",
            created_at=1,
        )
        session.commit()

        assert session.execute(select(CouncilRunRecord)).scalar_one().candidate_id == "candidate-1"
        assert (
            session.execute(select(EvidenceBundleRecord)).scalar_one().bundle_hash == "bundle-hash"
        )
        saved = session.execute(select(CouncilDecisionRecord)).scalar_one()
        assert saved.outcome == "hold"
        verdict_row = session.execute(select(AgentVerdictRecord)).scalar_one()
        assert verdict_row.raw_output_redacted is not None
        assert "secret" not in verdict_row.raw_output_redacted


def test_migration_is_idempotent_and_preserves_existing_paper_audit():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with Session(engine) as session:
        session.add(
            PaperRun(
                id="paper-1",
                domain="prediction",
                mode="shadow",
                asset_ids=["BTC"],
                started_at=1,
                status="running",
                config_fingerprint="config",
            )
        )
        session.add(
            PaperAuditEvent(
                paper_run_id="paper-1",
                kind="heartbeat",
                domain="prediction",
                asset_id="BTC",
                observed_at=1,
                status="ok",
            )
        )
        session.commit()

    create_all_tables(engine)
    with Session(engine) as session:
        assert session.execute(select(PaperRun)).scalar_one().id == "paper-1"
        assert session.execute(select(PaperAuditEvent)).scalar_one().kind == "heartbeat"
        assert session.execute(select(CouncilRunRecord)).all() == []


def test_council_lineage_rows_reject_updates_and_deletes():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with Session(engine) as session:
        append_council_run(
            session,
            run_id="run-immutable",
            candidate=_candidate(),
            profile=DEFAULT_COUNCIL_PROFILES[0],
            evidence=_evidence(),
            policy_version="1",
            created_at=1,
        )
        session.commit()
        run = session.get(CouncilRunRecord, "run-immutable")
        assert run is not None
        run.state = "completed"
        with pytest.raises(ValueError, match="append-only"):
            session.flush()
        session.rollback()
        run = session.get(CouncilRunRecord, "run-immutable")
        assert run is not None
        session.delete(run)
        with pytest.raises(ValueError, match="append-only"):
            session.flush()

    assert redact_payload({"token": "secret", "nested": {"private_key": "x"}}) == {
        "token": "[REDACTED]",
        "nested": {"private_key": "[REDACTED]"},
    }
