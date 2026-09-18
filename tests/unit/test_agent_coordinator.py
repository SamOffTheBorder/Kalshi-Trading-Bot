import json
import time

import pytest

from kalshi_bot.agents.contracts import (
    EvidenceBundle,
    EvidenceItem,
    TradeCandidateEnvelope,
)
from kalshi_bot.agents.coordinator import CouncilCoordinator, CouncilRoutingError
from kalshi_bot.agents.gateway import InProcessAgentClient
from kalshi_bot.agents.profiles import DEFAULT_COUNCIL_PROFILES


def _candidate() -> TradeCandidateEnvelope:
    return TradeCandidateEnvelope(
        candidate_id="candidate-1",
        domain="prediction",
        specialization_key="prediction/BTC/15m",
        instrument_id="KXBTC15M",
        strategy_name="fixture",
        strategy_version="strategy-1",
        decision_ts=100,
        proposed_action="BUY_YES",
        proposed_price=55,
        proposed_size=10,
        evidence_manifest_hash="manifest-1",
    )


def _evidence() -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id="bundle-1",
        candidate_id="candidate-1",
        domain="prediction",
        decision_ts=100,
        items=(
            EvidenceItem(
                evidence_id="e1",
                source="fixture",
                kind="quote",
                observed_at=99,
                available_at=99,
                content_hash="quote-hash",
                claim="quote is fresh",
            ),
        ),
        bundle_hash="bundle-hash",
    )


def _profile(**updates):
    profile = DEFAULT_COUNCIL_PROFILES[0].model_copy(update={"lifecycle": "fixture"})
    return profile.model_copy(update=updates)


def _verdict(request, *, decision="support", severity="info"):
    run_id = request.agent_id.split(":", 1)[0]
    return {
        "verdict_id": f"{run_id}-{request.role}-{request.attempt}",
        "council_run_id": run_id,
        "role": request.role,
        "specialization_key": "prediction/BTC/15m",
        "evidence_bundle_hash": "bundle-hash",
        "agent_snapshot_id": f"{run_id}:{request.role}",
        "decision": decision,
        "severity": severity,
        "confidence": 0.8,
        "claims": [{"claim": "supported by quote", "evidence_ids": ["e1"], "strength": 0.8}],
    }


def _clients(*, block_role=None, delays=None, master_calls=None, calls=None):
    delays = delays or {}
    clients = {}
    for role in (
        "researcher",
        "bull_thesis",
        "bear_thesis",
        "skeptic",
        "execution_liquidity",
        "rules_settlement",
        "portfolio_risk",
        "master_synthesizer",
    ):
        def handler(request, role=role):
            if calls is not None:
                calls.append(request)
            if delays.get(role):
                time.sleep(delays[role])
            if role == "master_synthesizer":
                if master_calls is not None:
                    master_calls.append(request)
                payload = request.payload
                verdicts = payload["validated_verdicts"]
                policy = payload["policy"]
                return {
                    "decision_id": f"{request.agent_id}-decision",
                    "council_run_id": request.agent_id.split(":", 1)[0],
                    "outcome": "take",
                    "selected_action": "BUY_YES",
                    "max_entry_price": 54,
                    "max_size": 8,
                    "summary": "validated take",
                    "supporting_verdict_ids": [verdicts[0]["verdict_id"]],
                    "dissenting_verdict_ids": [],
                    "policy": policy,
                }
            decision = (
                "block"
                if role == block_role
                else ("oppose" if role == "bear_thesis" else "support")
            )
            severity = "block" if role == block_role else "info"
            return _verdict(request, decision=decision, severity=severity)

        clients[role] = InProcessAgentClient(handler)
    return clients


def test_coordinator_routes_blind_roles_concurrently_and_synthesizes_deterministically():
    master_calls = []
    checkpoints = []
    coordinator = CouncilCoordinator(
        _clients(delays={"bull_thesis": 0.03, "bear_thesis": 0.01}, master_calls=master_calls),
        profiles=(_profile(),),
        checkpoint_fn=checkpoints.append,
    )
    result = coordinator.run(_candidate(), _evidence(), council_run_id="run-1")

    assert result.decision.outcome == "take"
    assert result.decision.selected_action == "BUY_YES"
    assert [attempt.role for attempt in result.attempts] == sorted(
        attempt.role for attempt in result.attempts
    )
    assert [
        attempt.role
        for attempt in result.attempts
        if attempt.role != "master_synthesizer"
    ] == [
        "bear_thesis",
        "bull_thesis",
        "execution_liquidity",
        "portfolio_risk",
        "researcher",
        "rules_settlement",
        "skeptic",
    ]
    assert len(master_calls) == 1
    assert "validated_verdicts" in master_calls[0].payload
    assert [checkpoint.stage for checkpoint in checkpoints] == [
        "evidence",
        "roles",
        "policy",
        "master",
        "completed",
    ]


def test_critical_block_wins_and_master_is_not_called():
    master_calls = []
    result = CouncilCoordinator(
        _clients(block_role="rules_settlement", master_calls=master_calls),
        profiles=(_profile(),),
    ).run(_candidate(), _evidence(), council_run_id="run-block")

    assert result.decision.outcome == "hold"
    assert "critical_veto" in result.policy.reason_codes
    assert master_calls == []


def test_missing_enabled_specialist_is_routing_failure():
    clients = _clients()
    for role in (
        "researcher",
        "bull_thesis",
        "bear_thesis",
        "skeptic",
        "execution_liquidity",
        "rules_settlement",
        "portfolio_risk",
    ):
        clients.pop(role)
    with pytest.raises(CouncilRoutingError, match="no enabled specialist"):
        CouncilCoordinator(clients, profiles=(_profile(),)).run(_candidate(), _evidence())


def test_master_cannot_change_action_or_loosen_candidate_bounds():
    clients = _clients()

    def unsafe_master(request):
        payload = request.payload
        return json.dumps(
            {
                "decision_id": "unsafe-decision",
                "council_run_id": request.agent_id.split(":", 1)[0],
                "outcome": "take",
                "selected_action": "BUY_NO",
                "max_entry_price": 99,
                "max_size": 100,
                "summary": "unsafe",
                "supporting_verdict_ids": [payload["validated_verdicts"][0]["verdict_id"]],
                "policy": payload["policy"],
            }
        )

    clients["master_synthesizer"] = InProcessAgentClient(unsafe_master)
    result = CouncilCoordinator(clients, profiles=(_profile(),)).run(
        _candidate(), _evidence(), council_run_id="run-unsafe"
    )
    assert result.decision.outcome == "hold"
    assert "master_changed_candidate_action" in result.decision.summary


def test_master_unknown_verdict_reference_fails_closed():
    clients = _clients()

    def fabricated_master(request):
        payload = request.payload
        return {
            "decision_id": "fabricated-decision",
            "council_run_id": request.agent_id.split(":", 1)[0],
            "outcome": "take",
            "selected_action": "BUY_YES",
            "summary": "fabricated support",
            "supporting_verdict_ids": ["not-a-real-verdict"],
            "policy": payload["policy"],
        }

    clients["master_synthesizer"] = InProcessAgentClient(fabricated_master)
    result = CouncilCoordinator(clients, profiles=(_profile(),)).run(
        _candidate(), _evidence(), council_run_id="run-fabricated"
    )
    assert result.decision.outcome == "hold"
    assert "unknown_supporting_verdict" in result.decision.summary


def test_reconsideration_is_one_bounded_revision_round():
    calls = []
    clients = _clients(calls=calls)

    result = CouncilCoordinator(clients, profiles=(_profile(),)).run(
        _candidate(),
        _evidence(),
        council_run_id="run-revision",
        enable_reconsideration=True,
    )
    revision_calls = [call for call in calls if call.attempt == 2]
    assert {call.role for call in revision_calls} == {"bull_thesis", "bear_thesis"}
    assert all(call.attempt <= 2 for call in calls)
    assert all("revision" in call.payload for call in revision_calls)
    assert all("validated_claims" in call.payload["revision"] for call in revision_calls)
    assert result.decision.outcome == "hold"
    assert "unresolved_disagreement" in result.policy.reason_codes
    assert not any(call.role == "master_synthesizer" for call in calls)


def test_budget_exhaustion_blocks_before_any_model_call():
    calls = []
    clients = _clients(calls=calls)
    budget = _profile().budget.model_copy(
        update={"total_output_tokens": 100, "total_cost_usd": 0.01}
    )
    result = CouncilCoordinator(
        clients,
        profiles=(_profile(budget=budget),),
    ).run(_candidate(), _evidence(), council_run_id="run-budget")
    assert result.decision.outcome == "hold"
    assert "critical_role_incomplete" in result.policy.reason_codes
    assert calls == []


def test_resume_skips_completed_role_artifacts_and_runs_remaining_roles():
    clients = _clients()
    first = CouncilCoordinator(clients, profiles=(_profile(),)).run(
        _candidate(), _evidence(), council_run_id="run-resume"
    )
    called = []
    clients = _clients(calls=called)
    resumed = CouncilCoordinator(clients, profiles=(_profile(),)).run(
        _candidate(),
        _evidence(),
        council_run_id="run-resume",
        completed_attempts=tuple(
            attempt for attempt in first.attempts if attempt.role != "master_synthesizer"
        ),
    )
    called_roles = [request.role for request in called]
    assert "researcher" not in called_roles
    assert "bull_thesis" not in called_roles
    assert "master_synthesizer" in called_roles
    assert resumed.decision.outcome == "take"
