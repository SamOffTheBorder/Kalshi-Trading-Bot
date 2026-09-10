"""Run-health and reconciliation reporting (multi-venue-paper-trading §12.4).

Covers: the six outcomes stay distinct (no_signal / policy_block / stale_data
/ missing_coverage / execution_rejected / system_failure); ledgers are
domain-separated and never merged; unresolved reconciliation blocks new
entries; an adapter error is a system failure; backtest divergence is
flagged past the threshold.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from kalshi_bot.execution.run_reporting import (
    EXECUTION_REJECTED,
    MISSING_COVERAGE,
    NO_SIGNAL,
    POLICY_BLOCK,
    STALE_DATA,
    SYSTEM_FAILURE,
    build_run_health_report,
    classify_status,
)
from kalshi_bot.storage import Base, PaperAuditEvent, PaperRun


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _run(session: Session, run_id="r", domain="prediction", status="completed") -> None:
    session.add(
        PaperRun(
            id=run_id,
            domain=domain,
            mode="paper",
            asset_ids=["BTC", "ETH"],
            started_at=1_000,
            ended_at=2_000,
            status=status,
            config_fingerprint="x",
        )
    )
    session.flush()


def _decision(session, *, run_id="r", domain="prediction", asset="BTC", status, ts=1_100):
    session.add(
        PaperAuditEvent(
            paper_run_id=run_id,
            kind="decision",
            domain=domain,
            asset_id=asset,
            observed_at=ts,
            status=status,
            reason=None,
            payload={},
        )
    )
    session.flush()


def _recon(session, *, run_id="r", domain="prediction", asset, status, reason, ts=1_200):
    session.add(
        PaperAuditEvent(
            paper_run_id=run_id,
            kind="reconciliation",
            domain=domain,
            asset_id=asset,
            observed_at=ts,
            status=status,
            reason=reason,
            payload={},
        )
    )
    session.flush()


def test_classify_status_covers_the_six_buckets():
    assert classify_status("hold") == NO_SIGNAL
    assert classify_status("admission_blocked") == POLICY_BLOCK
    assert classify_status("stale_quote") == STALE_DATA
    assert classify_status("no_listed_market") == MISSING_COVERAGE
    assert classify_status("order_rejected") == EXECUTION_REJECTED
    assert classify_status("adapter_error") == SYSTEM_FAILURE
    # An unknown named refusal is a policy block, never a healthy hold.
    assert classify_status("some_new_reason") == POLICY_BLOCK


def test_outcomes_stay_distinct_in_the_ledger(session):
    _run(session)
    _decision(session, status="hold")
    _decision(session, status="stale_quote")
    _decision(session, status="no_market")
    _decision(session, status="order_rejected")
    _decision(session, status="admission_blocked")
    _decision(session, status="adapter_error")
    report = build_run_health_report(session, "r")
    led = report.ledgers["prediction"]
    assert led.outcome_counts == {
        NO_SIGNAL: 1,
        STALE_DATA: 1,
        MISSING_COVERAGE: 1,
        EXECUTION_REJECTED: 1,
        POLICY_BLOCK: 1,
        SYSTEM_FAILURE: 1,
    }
    assert report.healthy is False
    assert report.system_failures == 1


def test_ledgers_are_domain_separated(session):
    _run(session, domain="prediction")
    _decision(session, domain="prediction", status="hold")
    # A stray perp decision recorded under the same run must not merge in.
    _decision(session, domain="perp", asset="BTC", status="filled")
    report = build_run_health_report(session, "r")
    assert set(report.ledgers) == {"prediction", "perp"}
    assert report.ledgers["prediction"].decisions == 1
    assert report.ledgers["perp"].fills == 1


def test_unresolved_reconciliation_blocks_new_entries(session):
    _run(session)
    _decision(session, status="hold")
    _recon(session, asset="BTC", status="reconciled", reason=None)
    _recon(session, asset="ETH", status="reconciliation_required", reason="orphan position")
    report = build_run_health_report(session, "r")
    assert [r.asset_id for r in report.unresolved_reconciliation] == ["ETH"]
    assert report.blocks_new_entries is True
    assert report.healthy is False


def test_latest_reconciliation_row_wins(session):
    _run(session)
    _recon(session, asset="BTC", status="reconciliation_required", reason="stale", ts=1_200)
    _recon(session, asset="BTC", status="reconciled", reason=None, ts=1_300)
    report = build_run_health_report(session, "r")
    assert report.unresolved_reconciliation == []
    assert report.blocks_new_entries is False


def test_quiet_run_with_only_holds_is_healthy(session):
    _run(session)
    for _ in range(5):
        _decision(session, status="hold")
    report = build_run_health_report(session, "r")
    assert report.healthy is True
    assert report.blocks_new_entries is False
    assert report.ledgers["prediction"].outcome_counts == {NO_SIGNAL: 5}


def test_backtest_divergence_is_flagged_past_threshold(session):
    _run(session)
    # 4 holds, 6 fills -> paper fill_rate 0.6
    for _ in range(4):
        _decision(session, status="hold")
    for _ in range(6):
        _decision(session, status="filled")
    report = build_run_health_report(
        session,
        "r",
        backtest_summary={"fill_rate": 0.2, "hold_rate": 0.8},
        divergence_threshold=0.15,
    )
    by_metric = {d.metric: d for d in report.divergence}
    assert by_metric["fill_rate"].exceeds is True
    assert by_metric["hold_rate"].exceeds is True


def test_unknown_run_raises(session):
    with pytest.raises(KeyError):
        build_run_health_report(session, "nope")
