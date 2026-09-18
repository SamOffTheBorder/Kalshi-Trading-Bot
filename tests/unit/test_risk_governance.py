"""Cross-domain emergency control + lifecycle governance
(multi-venue-paper-trading §11.4-11.7).

Covers: every trigger source routes to one durable halt; a halt blocks new
entries across all paper domains; global halt takes precedence over an
available domain budget; a simulated liquidation halts; resume refuses
without an operator or with an unresolved reconciliation condition; a fresh
process (new session, same DB) still sees the halt; promotion requires frozen
fingerprints and passing gates and cannot skip a stage or reach live;
demotion triggers move a single scope to blocked without touching siblings.
"""

from __future__ import annotations

import itertools

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from kalshi_bot.risk.governance import (
    GlobalEmergencyControl,
    HealthCheck,
    LifecycleGovernor,
    PromotionEvidence,
    PromotionRefusedError,
    ResumeRefusedError,
)
from kalshi_bot.risk.paper_policy import RiskRequest, admit_risk
from kalshi_bot.storage import Base, EmergencyHaltRecord, LifecycleTransitionRecord


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return eng


def _clock():
    counter = itertools.count(1_000)
    return lambda: next(counter)


def _control(session: Session) -> GlobalEmergencyControl:
    return GlobalEmergencyControl(
        session=session, now_fn=_clock(), policy_version="2026-09-paper-v1"
    )


def _evidence(**overrides) -> PromotionEvidence:
    values = dict(
        report_id="rep-1",
        data_manifest_hash="a" * 64,
        model_fingerprint="b" * 16,
        risk_policy_version="2026-09-paper-v1",
        gate_results={
            "data_coverage": True,
            "out_of_sample_validation": True,
            "execution_assumptions": True,
            "shadow_period": True,
            "paper_admission_report": True,
            "risk_policy": True,
        },
    )
    values.update(overrides)
    return PromotionEvidence(**values)


# --- emergency control --------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "operator",
        "drawdown",
        "daily_loss",
        "consecutive_loss",
        "liquidation",
        "margin_breach",
        "data_integrity",
        "process_signal",
        "reconciliation",
    ],
)
def test_every_trigger_source_routes_to_one_durable_halt(engine, source):
    with Session(engine) as session:
        ctl = _control(session)
        assert ctl.blocks_entry() is False
        status = ctl.halt(source=source, reason=f"{source} fired")
        assert status.halted is True
        assert status.source == source
        assert ctl.blocks_entry() is True
        rows = session.query(EmergencyHaltRecord).all()
        assert len(rows) == 1 and rows[0].action == "halt"


def test_halt_blocks_new_entries_across_every_paper_domain(engine):
    with Session(engine) as session:
        ctl = _control(session)
        ctl.halt(source="drawdown", reason="equity -12%")
        # The risk policy still passes on its own budgets...
        req = RiskRequest(
            domain="sports",
            asset_id="NFL",
            correlation_group="sports",
            market_id="KXNFLGAME",
            worst_case_loss_usd=5,
            data_age_seconds=10,
            reconciled=True,
        )
        assert admit_risk(req).allowed is True
        # ...but the global halt is checked first by callers and blocks all.
        assert ctl.blocks_entry() is True


def test_second_trigger_during_halt_keeps_first_halt_id_and_reason(engine):
    with Session(engine) as session:
        ctl = _control(session)
        first = ctl.halt(source="daily_loss", reason="-$30 today")
        again = ctl.halt(source="reconciliation", reason="orphan position")
        assert again.halt_id == first.halt_id
        assert again.source == "daily_loss"
        assert again.reason == "-$30 today"
        rows = session.query(EmergencyHaltRecord).order_by(EmergencyHaltRecord.id).all()
        assert [r.action for r in rows] == ["halt", "halt"]
        assert rows[1].reason.startswith("additional_trigger:")


def test_simulated_liquidation_halts_all_new_entries(engine):
    with Session(engine) as session:
        ctl = _control(session)
        ctl.halt(
            source="liquidation",
            reason="BTC perp liquidated",
            domain="perp",
            asset_id="BTC",
        )
        assert ctl.status().source == "liquidation"
        assert ctl.blocks_entry() is True


def test_resume_refused_without_operator(engine):
    with Session(engine) as session:
        ctl = _control(session)
        ctl.halt(source="operator", reason="manual")
        with pytest.raises(ResumeRefusedError):
            ctl.resume(operator="  ", health_check=HealthCheck.clean)


def test_resume_refused_while_unreconciled(engine):
    with Session(engine) as session:
        ctl = _control(session)
        ctl.halt(source="reconciliation", reason="stale open position")
        with pytest.raises(ResumeRefusedError) as exc:
            ctl.resume(
                operator="alice",
                health_check=lambda: HealthCheck(
                    healthy=False, unresolved=("BTC prediction position #7 unresolved",)
                ),
            )
        assert "unresolved" in str(exc.value)
        assert ctl.blocks_entry() is True


def test_resume_succeeds_with_operator_and_clean_check(engine):
    with Session(engine) as session:
        ctl = _control(session)
        ctl.halt(source="drawdown", reason="-15%")
        status = ctl.resume(operator="alice", health_check=HealthCheck.clean)
        assert status.halted is False
        assert ctl.blocks_entry() is False
        rows = session.query(EmergencyHaltRecord).order_by(EmergencyHaltRecord.id).all()
        assert [r.action for r in rows] == ["halt", "resume"]
        assert rows[1].operator == "alice"


def test_new_process_still_sees_the_halt(engine):
    with Session(engine) as session:
        _control(session).halt(source="process_signal", reason="SIGTERM")
        session.commit()
    # A completely fresh control on a new session (models a process restart).
    with Session(engine) as session:
        ctl = _control(session)
        assert ctl.blocks_entry() is True
        assert ctl.status().source == "process_signal"


def test_unknown_halt_source_rejected(engine):
    with Session(engine) as session, pytest.raises(ValueError):
        _control(session).halt(source="cosmic_ray", reason="bit flip")


# --- lifecycle promotion / demotion ----------------------------------


def test_promotion_advances_one_stage_with_frozen_evidence(engine):
    with Session(engine) as session:
        gov = LifecycleGovernor(session=session, now_fn=_clock(), default_state="observe")
        assert gov.current_state("BTC", "prediction", "kxbtc15m") == "observe"
        gov.promote(
            asset_id="BTC",
            domain="prediction",
            candidate="kxbtc15m",
            to_state="backtest",
            operator="alice",
            evidence=_evidence(),
        )
        assert gov.current_state("BTC", "prediction", "kxbtc15m") == "backtest"


def test_promotion_cannot_skip_a_stage(engine):
    with Session(engine) as session:
        gov = LifecycleGovernor(session=session, now_fn=_clock())
        with pytest.raises(PromotionRefusedError):
            gov.promote(
                asset_id="BTC",
                domain="prediction",
                candidate="c",
                to_state="paper",  # observe -> paper skips backtest/shadow
                operator="alice",
                evidence=_evidence(),
            )


def test_promotion_rejects_missing_fingerprints(engine):
    with Session(engine) as session:
        gov = LifecycleGovernor(session=session, now_fn=_clock())
        with pytest.raises(PromotionRefusedError):
            gov.promote(
                asset_id="ETH",
                domain="prediction",
                candidate="c",
                to_state="backtest",
                operator="alice",
                evidence=_evidence(data_manifest_hash=""),
            )


def test_promotion_rejects_failing_gate(engine):
    with Session(engine) as session:
        gov = LifecycleGovernor(session=session, now_fn=_clock())
        ev = _evidence()
        ev.gate_results["shadow_period"] = False
        with pytest.raises(PromotionRefusedError):
            gov.promote(
                asset_id="SOL",
                domain="prediction",
                candidate="c",
                to_state="backtest",
                operator="alice",
                evidence=ev,
            )


def test_no_promotion_target_is_live(engine):
    with Session(engine) as session:
        gov = LifecycleGovernor(session=session, now_fn=_clock())
        with pytest.raises(ValueError):
            gov.promote(
                asset_id="BTC",
                domain="prediction",
                candidate="c",
                to_state="live",  # not a defined lifecycle state
                operator="alice",
                evidence=_evidence(),
            )


def test_demotion_blocks_one_scope_without_touching_siblings(engine):
    with Session(engine) as session:
        gov = LifecycleGovernor(session=session, now_fn=_clock(), default_state="shadow")
        gov.demote(
            asset_id="BTC",
            domain="prediction",
            candidate="c",
            trigger="paper_backtest_divergence",
            reason="fills diverged 40% from frozen backtest",
        )
        assert gov.current_state("BTC", "prediction", "c") == "blocked"
        # ETH and the BTC perp scope are untouched.
        assert gov.current_state("ETH", "prediction", "c") == "shadow"
        assert gov.current_state("BTC", "perp", "c") == "shadow"
        rows = session.query(LifecycleTransitionRecord).all()
        assert len(rows) == 1 and rows[0].direction == "demote"


def test_emergency_halt_demotes_affected_scope(engine):
    with Session(engine) as session:
        gov = LifecycleGovernor(session=session, now_fn=_clock(), default_state="paper")
        gov.demote(
            asset_id="BTC",
            domain="perp",
            candidate="c",
            trigger="emergency_halt",
            reason="liquidation halt",
        )
        assert gov.current_state("BTC", "perp", "c") == "blocked"


def test_unknown_demotion_trigger_rejected(engine):
    with Session(engine) as session:
        gov = LifecycleGovernor(session=session, now_fn=_clock())
        with pytest.raises(ValueError):
            gov.demote(
                asset_id="BTC",
                domain="perp",
                candidate="c",
                trigger="vibes",
                reason="felt wrong",
            )


def test_blocked_scope_needs_review_before_promotion(engine):
    with Session(engine) as session:
        gov = LifecycleGovernor(session=session, now_fn=_clock(), default_state="shadow")
        gov.demote(
            asset_id="BTC",
            domain="prediction",
            candidate="c",
            trigger="data_integrity_failure",
            reason="checksum mismatch",
        )
        with pytest.raises(PromotionRefusedError):
            gov.promote(
                asset_id="BTC",
                domain="prediction",
                candidate="c",
                to_state="paper",
                operator="alice",
                evidence=_evidence(),
            )
