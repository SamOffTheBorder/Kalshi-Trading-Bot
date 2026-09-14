from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from kalshi_bot.agents.contracts import EvidenceBundle, TradeCandidateEnvelope
from kalshi_bot.agents.evaluation import (
    EvaluationReport,
    OutcomeBlindReplayRunner,
    ReplaySample,
    compare_variants,
    compute_metrics,
    evaluate_promotion,
    freeze_evaluation_plan,
)
from kalshi_bot.agents.lifecycle import (
    CouncilLifecycleStore,
    ProfilePromotionRefusedError,
    PromotionReport,
)
from kalshi_bot.storage import CouncilProfileLifecycleRecord
from kalshi_bot.storage.models import Base


def _candidate() -> TradeCandidateEnvelope:
    return TradeCandidateEnvelope(
        candidate_id="c1",
        domain="prediction",
        specialization_key="prediction/BTC/15m",
        instrument_id="MKT-1",
        strategy_name="fixture",
        strategy_version="1",
        decision_ts=100,
        proposed_action="BUY_YES",
        evidence_manifest_hash="manifest",
    )


def _evidence() -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id="b1",
        candidate_id="c1",
        domain="prediction",
        decision_ts=100,
        bundle_hash="evidence",
    )


def test_profile_lifecycle_is_explicit_one_step_and_append_only():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        store = CouncilLifecycleStore(session, now_fn=lambda: 10)
        report = PromotionReport("r1", "profile", "1", True, 1, 2, {"schema": True})
        assert store.promote(
            profile_id="profile",
            profile_version="1",
            to_state="fixture",
            operator="operator",
            report=report,
        ) == "fixture"
        with pytest.raises(ProfilePromotionRefusedError, match="exactly one"):
            store.promote(
                profile_id="profile",
                profile_version="1",
                to_state="shadow",
                operator="operator",
                report=report,
            )
        assert store.demote(
            profile_id="profile",
            profile_version="1",
            to_state="disabled",
            reason="operator rollback",
            operator="operator",
        ) == "disabled"
        session.commit()
        assert len(store.history("profile")) == 2
        assert session.execute(select(CouncilProfileLifecycleRecord)).all()


def test_profile_promotion_rejects_late_or_unfrozen_report():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        store = CouncilLifecycleStore(session, now_fn=lambda: 1)
        report = PromotionReport("r1", "profile", "1", True, 10, 10, {"schema": True})
        with pytest.raises(ProfilePromotionRefusedError, match="frozen passing"):
            store.promote(
                profile_id="profile",
                profile_version="1",
                to_state="fixture",
                operator="operator",
                report=report,
            )


def test_outcome_blind_replay_joins_realized_outcomes_after_decisions():
    samples = (
        ReplaySample("s1", _candidate(), _evidence(), realized_return_usd=2.0, outcome=True),
    )
    seen = []

    def council(candidate, evidence):
        seen.append((candidate, evidence))
        return SimpleNamespace(
            decision=SimpleNamespace(outcome="take"),
            cost_usd=0.1,
            attempts=(),
        )

    observations = OutcomeBlindReplayRunner().run(
        samples,
        council_fn=council,
        baseline_fn=lambda candidate, evidence: "hold",
        single_agent_fn=lambda candidate, evidence: "take",
    )
    assert seen == [(_candidate(), _evidence())]
    assert observations[0].realized_return_usd == 2.0
    assert observations[0].council_outcome == "take"


def test_metrics_and_promotion_require_net_gain_and_component_evidence():
    from kalshi_bot.agents.evaluation import ReplayObservation

    observations = (
        ReplayObservation(
            "s1",
            "take",
            "hold",
            "take",
            2.0,
            True,
            False,
            True,
            latency_ms=5,
            model_cost_usd=0.1,
            component="BTC",
        ),
        ReplayObservation(
            "s2",
            "take",
            "take",
            "take",
            -1.0,
            True,
            False,
            True,
            latency_ms=7,
            model_cost_usd=0.1,
            component="BTC",
        ),
    )
    metrics = compute_metrics(observations)
    assert metrics.false_approvals == 1
    assert metrics.model_cost_usd == pytest.approx(0.2)
    plan = freeze_evaluation_plan(
        profile_id="prediction-btc-15m",
        profile_version="1",
        evaluation_window="heldout-1",
        sample_minimum=2,
        thresholds={"min_incremental_value": 0.0, "max_false_approvals": 0},
        evidence_manifest_hash="manifest",
        policy_version="policy-1",
        prompt_hash="prompt",
        model_assignments={"master": "gpt"},
        code_revision="rev-1",
        random_seed=7,
        registered_at=1,
    )
    report = EvaluationReport(
        plan,
        heldout_completed_at=2,
        metrics=metrics,
        component_metrics={"BTC": metrics},
    )
    passed, reasons = evaluate_promotion(report)
    assert not passed
    assert "false_approval_threshold" in reasons
    assert "component_failure:BTC" in reasons


def test_variant_comparison_requires_same_samples_and_reports_error_correlation():
    from kalshi_bot.agents.evaluation import ReplayObservation

    champion = (
        ReplayObservation("s1", "take", "hold", "take", -1.0, True, False, True),
        ReplayObservation("s2", "hold", "hold", "hold", 1.0, True, False, True),
    )
    challenger = (
        ReplayObservation("s1", "hold", "hold", "hold", -1.0, True, False, True),
        ReplayObservation("s2", "take", "hold", "take", 1.0, True, False, True),
    )
    comparison = compare_variants(champion, challenger)
    assert comparison.challenger_incremental_value > comparison.champion.net_result_after_costs
    with pytest.raises(ValueError, match="identical sample set"):
        compare_variants(champion, challenger[:1])
