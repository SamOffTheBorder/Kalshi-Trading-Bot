from types import SimpleNamespace

import pytest

from kalshi_bot.agents.admission import (
    AdmissionCheck,
    CouncilPaperBoundary,
    deterministic_prescreen,
    validate_council_mode,
)
from kalshi_bot.agents.contracts import TradeCandidateEnvelope


def _candidate(domain="prediction") -> TradeCandidateEnvelope:
    action = "BUY_YES" if domain in {"prediction", "sports"} else "LONG"
    specialization = {
        "prediction": "prediction/BTC/15m",
        "perp": "perp/BTC/directional",
        "sports": "sports/NFL/game/moneyline",
    }[domain]
    return TradeCandidateEnvelope(
        candidate_id="candidate-1",
        domain=domain,
        specialization_key=specialization,
        instrument_id="MKT-1",
        strategy_name="fixture",
        strategy_version="1",
        decision_ts=100,
        proposed_action=action,
        proposed_price=55,
        proposed_size=10,
        evidence_manifest_hash="manifest-1",
    )


def _council(outcome="take", price=50, size=4):
    return SimpleNamespace(
        decision=SimpleNamespace(
            outcome=outcome,
            decision_id="decision-1",
            max_entry_price=price if outcome == "take" else None,
            max_size=size if outcome == "take" else None,
        ),
        policy=SimpleNamespace(policy_version="policy-1"),
    )


def test_prescreen_failure_skips_council_and_is_explicit():
    result = deterministic_prescreen(
        _candidate(),
        (lambda _candidate: AdmissionCheck("freshness", False, "stale_quote"),),
    )
    assert not result.allowed
    assert result.status == "hold"
    assert result.reason_codes == ("stale_quote",)

    called = []
    boundary = CouncilPaperBoundary(
        mode="paper_advisory",
        pre_checks=(lambda _candidate: AdmissionCheck("freshness", False, "stale_quote"),),
    )
    outcome = boundary.review(
        _candidate(),
        run_council=lambda _candidate: called.append(True),
        adapter_fn=lambda _candidate: called.append("adapter"),
    )
    assert outcome.status == "hold"
    assert called == []
    assert outcome.stages == ("initial_screen",)


def test_shadow_records_council_without_adapter_influence():
    called = []
    outcome = CouncilPaperBoundary(mode="shadow").review(
        _candidate(),
        run_council=lambda candidate: _council(),
        adapter_fn=lambda candidate: called.append(candidate),
    )
    assert outcome.status == "shadow_recorded"
    assert called == []
    assert outcome.reason_codes == ("shadow_no_paper_influence",)


def test_advisory_tightens_bounds_and_requires_final_recheck():
    received = []
    audited = []
    outcome = CouncilPaperBoundary(
        mode="paper_advisory",
        final_checks=(lambda candidate: AdmissionCheck("risk", True),),
        audit_fn=lambda stage, payload: audited.append((stage, payload)),
    ).review(
        _candidate(),
        run_council=lambda candidate: _council(price=50, size=4),
        adapter_fn=lambda candidate: received.append(candidate) or "simulated",
    )
    assert outcome.status == "adapter_called"
    assert received[0].proposed_price == 50
    assert received[0].proposed_size == 4
    assert [stage for stage, _payload in audited] == [
        "initial_screen",
        "council_recommendation",
        "final_recheck",
        "adapter_decision",
    ]

    blocked = CouncilPaperBoundary(
        mode="paper_advisory",
        final_checks=(lambda candidate: AdmissionCheck("quote", False, "quote_expired"),),
    ).review(
        _candidate(),
        run_council=lambda candidate: _council(),
        adapter_fn=lambda candidate: pytest.fail("adapter must not be called"),
    )
    assert blocked.status == "hold"
    assert blocked.reason_codes == ("quote_expired",)


def test_council_hold_never_reaches_adapter_and_live_mode_is_rejected():
    outcome = CouncilPaperBoundary(mode="paper_council").review(
        _candidate(),
        run_council=lambda candidate: _council(outcome="hold"),
        adapter_fn=lambda candidate: pytest.fail("adapter must not be called"),
    )
    assert outcome.status == "hold"
    assert outcome.reason_codes == ("council_hold",)
    with pytest.raises(ValueError, match="unavailable for live"):
        validate_council_mode("live")


@pytest.mark.parametrize("domain", ["prediction", "perp", "sports"])
def test_final_deterministic_refusal_wins_over_council_take_for_every_domain(domain):
    called = []
    outcome = CouncilPaperBoundary(
        mode="paper_advisory",
        final_checks=(lambda candidate: AdmissionCheck("risk", False, "risk_refusal"),),
    ).review(
        _candidate(domain),
        run_council=lambda candidate: _council(),
        adapter_fn=lambda candidate: called.append(candidate),
    )
    assert outcome.status == "hold"
    assert outcome.reason_codes == ("risk_refusal",)
    assert called == []
