from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from kalshi_bot.agents.btc_rollout import (
    BTC_FIXTURES,
    BTC_PROFILE_ID,
    btc_fixture_profile,
    build_btc_shadow_report,
    promote_btc_to_shadow,
    run_btc_fixture_suite,
)
from kalshi_bot.agents.evaluation import ReplayObservation, freeze_evaluation_plan
from kalshi_bot.agents.lifecycle import CouncilLifecycleStore
from kalshi_bot.storage.models import Base


def test_btc_rollout_is_the_only_initial_profile_and_fixture_suite_is_explicit():
    profile = btc_fixture_profile()
    assert profile.profile_id == BTC_PROFILE_ID
    assert profile.lifecycle == "fixture"
    results = run_btc_fixture_suite(lambda fixture: fixture.expected)
    assert len(results) == 9
    assert {fixture.name for fixture in BTC_FIXTURES} == {result[0] for result in results}


def test_btc_promotion_requires_frozen_positive_shadow_report_and_advances_one_step():
    plan = freeze_evaluation_plan(
        profile_id=BTC_PROFILE_ID,
        profile_version="1",
        evaluation_window="btc-shadow-heldout",
        sample_minimum=1,
        thresholds={"min_incremental_value": 0.0},
        evidence_manifest_hash="manifest-btc",
        policy_version="policy-btc",
        prompt_hash="prompt-btc",
        model_assignments={"master": "gpt-6-astra"},
        code_revision="revision-btc",
        random_seed=15,
        registered_at=1,
    )
    observations = (
        ReplayObservation(
            "btc-take",
            "take",
            "hold",
            "hold",
            2.0,
            True,
            False,
            True,
            component=BTC_PROFILE_ID,
        ),
    )
    report = build_btc_shadow_report(plan, observations)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        store = CouncilLifecycleStore(session, now_fn=lambda: 10)
        assert promote_btc_to_shadow(store, operator="operator", report=report) == "shadow"
        assert store.current_state(BTC_PROFILE_ID) == "shadow"
        assert [row.to_state for row in store.history(BTC_PROFILE_ID)] == [
            "fixture",
            "replay",
            "shadow",
        ]
