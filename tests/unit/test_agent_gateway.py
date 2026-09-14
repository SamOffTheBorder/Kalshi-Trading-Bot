from __future__ import annotations

import time

from kalshi_bot.agents.contracts import (
    AgentVerdictArtifact,
    EvidenceBundle,
    EvidenceClaim,
    EvidenceItem,
)
from kalshi_bot.agents.gateway import AgentRequest, InProcessAgentClient, format_repair_request
from kalshi_bot.agents.profiles import DEFAULT_COUNCIL_PROFILES
from kalshi_bot.agents.validation import validate_verdict_artifact


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id="b1",
        candidate_id="c1",
        domain="prediction",
        decision_ts=100,
        items=(
            EvidenceItem(
                evidence_id="e1",
                source="fixture",
                kind="quote",
                observed_at=99,
                available_at=99,
                content_hash="h",
                claim="quote",
            ),
        ),
        bundle_hash="bundle",
    )


def _request(timeout=1.0):
    return AgentRequest("skeptic", "agent-1", {"safe": True}, timeout, 100, 1)


def test_in_process_gateway_is_deterministic_and_repairs_without_new_evidence():
    client = InProcessAgentClient(lambda request: {"request_hash": request.request_hash})
    result = client.invoke(_request())
    assert result.status == "completed"
    assert result.request_hash in result.raw_output
    repair = format_repair_request(_request(), "bad", ["unknown_evidence"])
    assert repair.attempt == 2
    assert repair.payload == {
        "repair": {"original_output": "bad", "schema_errors": ["unknown_evidence"]}
    }


def test_in_process_gateway_times_out_without_waiting_for_handler():
    def slow(_request):
        time.sleep(0.2)
        return "{}"

    result = InProcessAgentClient(slow).invoke(_request(timeout=0.01))
    assert result.status == "timeout"


def test_in_process_gateway_captures_provider_failure_and_invalid_response():
    def fail(_request):
        raise RuntimeError("provider")

    failed = InProcessAgentClient(fail).invoke(_request())
    assert failed.status == "failed"
    assert failed.error == "RuntimeError:provider"

    invalid = InProcessAgentClient(lambda _request: 42).invoke(_request())
    assert invalid.status == "invalid_response"
    assert invalid.error == "handler_returned_unsupported_type"


def test_in_process_gateway_enforces_response_size_limit():
    result = InProcessAgentClient(lambda _request: "x" * 2_000).invoke(
        _request()
    )
    assert result.status == "response_too_large"


def test_verdict_validation_rejects_unknown_evidence_and_unauthorized_size():
    verdict = AgentVerdictArtifact(
        verdict_id="v1",
        council_run_id="run",
        role="skeptic",
        specialization_key="prediction/BTC/15m",
        evidence_bundle_hash="bundle",
        agent_snapshot_id="agent",
        decision="support",
        severity="info",
        confidence=0.5,
        claims=(EvidenceClaim(claim="bad", evidence_ids=("missing",), strength=1.0),),
        size_ceiling=1,
    )
    errors = validate_verdict_artifact(
        verdict,
        bundle=_bundle(),
        role_config=next(
            role for role in DEFAULT_COUNCIL_PROFILES[0].roles if role.role == "skeptic"
        ),
    )
    assert "unknown_evidence:missing" in errors
    assert "role_cannot_propose_size_ceiling" in errors
