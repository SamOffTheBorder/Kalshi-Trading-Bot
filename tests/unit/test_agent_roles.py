from dataclasses import dataclass

from kalshi_bot.agents.contracts import TradeCandidateEnvelope
from kalshi_bot.agents.prompts import ROLE_MANDATES, build_role_prompt
from kalshi_bot.agents.roles import LocalReviewSkepticRole, sports_research_to_verdict
from kalshi_bot.ai.local_review import VetoVerdict
from kalshi_bot.ai.sports_research import EvidenceSummary


@dataclass
class FakeLocalReview:
    verdict: VetoVerdict

    def review(self, _candidate):
        return self.verdict


def _candidate(domain: str = "prediction") -> TradeCandidateEnvelope:
    return TradeCandidateEnvelope(
        candidate_id="c1",
        domain=domain,
        specialization_key=(
            "prediction/BTC/15m" if domain == "prediction" else "sports/NFL/game"
        ),
        instrument_id="MKT-1",
        strategy_name="fixture",
        strategy_version="1",
        decision_ts=100,
        proposed_action="BUY_YES",
        proposed_price=55,
        evidence_manifest_hash="manifest-1",
    )


def test_local_review_role_preserves_fail_closed_verdict_and_legacy_linkage():
    legacy = VetoVerdict(
        approved=False,
        reason="malformed_response",
        confidence=None,
        raw_response="{bad",
        latency_ms=7,
    )
    result = LocalReviewSkepticRole(
        FakeLocalReview(legacy),
        council_run_id="run-1",
        evidence_bundle_hash="evidence-1",
        agent_snapshot_id="agent-1",
    ).review(_candidate())

    assert result.verdict.role == "skeptic"
    assert result.verdict.decision == "block"
    assert result.verdict.severity == "block"
    assert result.verdict.reason_codes == ("legacy_veto_rejected",)
    assert result.legacy_verdict is legacy
    assert result.legacy_record is not None


def test_local_review_role_refuses_non_prediction_without_calling_client():
    class ExplodingClient:
        def review(self, _candidate):
            raise AssertionError("non-prediction must not call legacy client")

    result = LocalReviewSkepticRole(
        ExplodingClient(),
        council_run_id="run-1",
        evidence_bundle_hash="evidence-1",
        agent_snapshot_id="agent-1",
    ).review(_candidate("sports"))
    assert result.verdict.decision == "block"


def test_sports_research_maps_to_non_voting_evidence_linked_artifact():
    summary = EvidenceSummary(
        market_ticker="NFL-MKT",
        provider="fixture",
        model="fixture",
        summary="Weather supports the supplied thesis.",
        classification="supportive",
        citations=("card-1",),
        prompt_hash="prompt",
        output_hash="output",
        available=True,
        status="ok",
        latency_ms=3,
        retrieved_at=100,
    )
    verdict = sports_research_to_verdict(
        summary,
        council_run_id="run-1",
        specialization_key="sports/NFL/game",
        evidence_bundle_hash="evidence-1",
        agent_snapshot_id="agent-1",
        evidence_ids=("card-1",),
    )
    assert verdict.role == "researcher"
    assert verdict.decision == "support"
    assert verdict.proposed_action is None
    assert verdict.claims[0].evidence_ids == ("card-1",)


def test_every_role_prompt_is_mandate_bound_and_evidence_only():
    for role, mandate in ROLE_MANDATES.items():
        prompt = build_role_prompt(role, {"evidence_ids": ["e1"]})
        assert mandate in prompt
        assert "supplied evidence" in prompt
        assert "schema" in prompt
