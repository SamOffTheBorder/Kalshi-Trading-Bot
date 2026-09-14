"""Conservative BTC 15-minute council fixture and shadow-rollout helpers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from kalshi_bot.agents.contracts import CouncilOutcome, EvidenceBundle, TradeCandidateEnvelope
from kalshi_bot.agents.evaluation import EvaluationReport, ReplayObservation, compute_metrics
from kalshi_bot.agents.lifecycle import CouncilLifecycleStore, PromotionReport
from kalshi_bot.agents.profiles import DEFAULT_COUNCIL_PROFILES, CouncilProfile

BTC_PROFILE_ID = "prediction-btc-15m"


@dataclass(frozen=True)
class BtcFixture:
    name: str
    expected: CouncilOutcome
    candidate: TradeCandidateEnvelope
    evidence: EvidenceBundle
    notes: tuple[str, ...] = ()


def btc_fixture_profile() -> CouncilProfile:
    profile = next(
        profile for profile in DEFAULT_COUNCIL_PROFILES if profile.profile_id == BTC_PROFILE_ID
    )
    return profile.model_copy(update={"lifecycle": "fixture", "allow_paper_influence": False})


def _fixture(
    name: str,
    expected: CouncilOutcome,
    *,
    missing=(),
    conflicts=(),
    notes=(),
) -> BtcFixture:
    candidate = TradeCandidateEnvelope(
        candidate_id=f"btc-fixture-{name}",
        domain="prediction",
        specialization_key="prediction/BTC/15m",
        instrument_id="KXBTC15M",
        strategy_name="btc-15m-fixture",
        strategy_version="fixture-v1",
        decision_ts=1_700_000_000,
        proposed_action="BUY_YES",
        proposed_price=50,
        proposed_size=1,
        horizon_seconds=900,
        settlement_rule_id="kalshi-binary-v1",
        evidence_manifest_hash=f"manifest-{name}",
    )
    evidence = EvidenceBundle(
        bundle_id=f"bundle-{name}",
        candidate_id=candidate.candidate_id,
        domain="prediction",
        decision_ts=candidate.decision_ts,
        missing_fields=tuple(missing),
        conflict_fields=tuple(conflicts),
        bundle_hash=f"bundle-hash-{name}",
    )
    return BtcFixture(name, expected, candidate, evidence, tuple(notes))


BTC_FIXTURES: tuple[BtcFixture, ...] = (
    _fixture("take", "take", notes=("fresh quote", "quorum")),
    _fixture("reject", "reject", conflicts=("settlement_rule",)),
    _fixture("insufficient-evidence", "hold", missing=("quote", "brti")),
    _fixture("stale-quote", "hold", notes=("quote_expired",)),
    _fixture("settlement-ambiguity", "hold", conflicts=("resolution_source",)),
    _fixture("bull-bear-conflict", "hold", notes=("unresolved_disagreement",)),
    _fixture("prompt-injection", "hold", notes=("untrusted_source_text",)),
    _fixture("timeout", "hold", notes=("critical_role_timeout",)),
    _fixture("risk-refusal", "hold", notes=("concentration_limit",)),
)


def run_btc_fixture_suite(
    decision_fn: Callable[[BtcFixture], CouncilOutcome],
    fixtures: Sequence[BtcFixture] = BTC_FIXTURES,
) -> tuple[tuple[str, CouncilOutcome, CouncilOutcome], ...]:
    results: tuple[tuple[str, CouncilOutcome, CouncilOutcome], ...] = tuple(
        (fixture.name, fixture.expected, decision_fn(fixture)) for fixture in fixtures
    )
    failures = [name for name, expected, actual in results if expected != actual]
    if failures:
        raise AssertionError(f"BTC fixture expectations failed: {failures}")
    return results


def build_btc_shadow_report(
    plan,
    observations: Sequence[ReplayObservation],
) -> EvaluationReport:
    metrics = compute_metrics(observations)
    components = {component: compute_metrics(
        [observation for observation in observations if observation.component == component]
    ) for component in sorted({observation.component for observation in observations})}
    return EvaluationReport(
        plan,
        heldout_completed_at=plan.registered_at + 1,
        metrics=metrics,
        component_metrics=components,
    )


def promote_btc_to_shadow(
    store: CouncilLifecycleStore,
    *,
    operator: str,
    report: EvaluationReport,
) -> str:
    passed = report.metrics.incremental_value > 0 and bool(report.component_metrics)
    if not passed:
        raise ValueError("BTC shadow promotion requires a passing frozen report")
    evidence = PromotionReport(
        report_id=report.plan.plan_hash,
        profile_id=report.plan.profile_id,
        profile_version=report.plan.profile_version,
        frozen=True,
        registered_at=report.plan.registered_at,
        heldout_completed_at=report.heldout_completed_at,
        gate_results={"btc_shadow_report": True},
    )
    if store.current_state(BTC_PROFILE_ID) == "disabled":
        store.promote(
            profile_id=BTC_PROFILE_ID,
            profile_version=report.plan.profile_version,
            to_state="fixture",
            operator=operator,
            report=evidence,
        )
    if store.current_state(BTC_PROFILE_ID) == "fixture":
        store.promote(
            profile_id=BTC_PROFILE_ID,
            profile_version=report.plan.profile_version,
            to_state="replay",
            operator=operator,
            report=evidence,
        )
    return store.promote(
        profile_id=BTC_PROFILE_ID,
        profile_version=report.plan.profile_version,
        to_state="shadow",
        operator=operator,
        report=evidence,
    )


__all__ = [
    "BTC_FIXTURES",
    "BTC_PROFILE_ID",
    "BtcFixture",
    "btc_fixture_profile",
    "build_btc_shadow_report",
    "promote_btc_to_shadow",
    "run_btc_fixture_suite",
]
