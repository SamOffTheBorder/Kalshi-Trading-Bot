from __future__ import annotations

import pytest
from pydantic import ValidationError

from kalshi_bot.agents.contracts import EvidenceBundle, EvidenceItem, TradeCandidateEnvelope
from kalshi_bot.agents.profiles import (
    DEFAULT_COUNCIL_PROFILES,
    CouncilBudget,
    CouncilProfile,
    ModelAssignment,
    resolve_profile,
)


def _candidate(**changes):
    values = dict(
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
        evidence_manifest_hash="manifest-hash",
    )
    values.update(changes)
    return TradeCandidateEnvelope(**values)


def test_candidate_contract_rejects_cross_domain_action():
    with pytest.raises(ValidationError, match="prediction candidates"):
        _candidate(proposed_action="LONG")


def test_evidence_bundle_rejects_late_or_duplicate_evidence():
    item = EvidenceItem(
        evidence_id="e1",
        source="fixture",
        kind="quote",
        observed_at=10,
        available_at=11,
        content_hash="hash",
        claim="quote exists",
    )
    with pytest.raises(ValidationError, match="unavailable"):
        EvidenceBundle(
            bundle_id="b1",
            candidate_id="candidate-1",
            domain="prediction",
            decision_ts=10,
            items=(item,),
            bundle_hash="bundle-hash",
        )

    duplicate = item.model_copy(update={"available_at": 10})
    with pytest.raises(ValidationError, match="unique"):
        EvidenceBundle(
            bundle_id="b1",
            candidate_id="candidate-1",
            domain="prediction",
            decision_ts=10,
            items=(duplicate, duplicate),
            bundle_hash="bundle-hash",
        )


def test_exact_profile_beats_wildcard_profile():
    profile = resolve_profile("prediction/BTC/15m")
    assert profile is not None
    assert profile.profile_id == "prediction-btc-15m"
    assert resolve_profile("prediction/ETH/60m").profile_id == "prediction-crypto-cadence"


def test_profile_rejects_missing_roles_and_a2a_without_card():
    with pytest.raises(ValidationError, match="missing required roles"):
        CouncilProfile(
            profile_id="bad",
            version="1",
            domain="prediction",
            specialization_pattern="prediction/BTC/15m",
            budget=CouncilBudget(
                total_timeout_seconds=10,
                total_output_tokens=100,
                total_cost_usd=1,
                max_concurrency=1,
                max_reconsideration_rounds=0,
                max_format_retries=0,
            ),
        )

    with pytest.raises(ValidationError, match="Agent Card URI"):
        CouncilProfile(
            profile_id="bad-a2a",
            version="1",
            domain="prediction",
            specialization_pattern="prediction/BTC/15m",
            transport="a2a",
            roles=DEFAULT_COUNCIL_PROFILES[0].roles,
            budget=DEFAULT_COUNCIL_PROFILES[0].budget,
        )


def test_model_assignment_rejects_unknown_provider():
    with pytest.raises(ValidationError):
        ModelAssignment(provider="unknown", model="model")
