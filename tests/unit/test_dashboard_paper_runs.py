"""Dashboard paper-run overview + eligibility guards
(multi-venue-paper-trading §12.1 / §12.2).

Covers: the all-domain overview summarizes each run's health and
reconciliation state; the `ops` command-audit run is excluded; a domain
filter keeps ledgers separated; an unresolved reconciliation surfaces as
`blocks_new_entries`; and no discovery state ever lets sports render as an
eligible/tradeable domain.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kalshi_bot.storage import Base, PaperAuditEvent, PaperRun
from kalshi_bot.web.queries import (
    asset_admissions,
    domain_paper_runs,
    market_areas,
    paper_runs_overview,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _run(session, run_id, domain, *, mode="paper", status="completed", started=1_000):
    session.add(
        PaperRun(
            id=run_id,
            domain=domain,
            mode=mode,
            asset_ids=["BTC"],
            started_at=started,
            ended_at=started + 100,
            status=status,
            config_fingerprint="x",
        )
    )
    session.flush()


def _event(session, run_id, domain, kind, status, *, asset="BTC", reason=None, ts=1_050):
    session.add(
        PaperAuditEvent(
            paper_run_id=run_id,
            kind=kind,
            domain=domain,
            asset_id=asset,
            observed_at=ts,
            status=status,
            reason=reason,
            payload={},
        )
    )
    session.flush()


def test_overview_summarizes_health_and_excludes_ops_run(session):
    _run(session, "p1", "prediction", started=2_000)
    _event(session, "p1", "prediction", "decision", "hold")
    _run(session, "ops-20260909", "ops", started=3_000)
    _event(session, "ops-20260909", "ops", "operator_command", "ok")

    rows = paper_runs_overview(session)
    assert [r.run_id for r in rows] == ["p1"]
    assert rows[0].domain == "prediction"
    assert rows[0].healthy is True
    assert rows[0].decisions == 1


def test_overview_orders_newest_first_and_filters_by_domain(session):
    _run(session, "p1", "prediction", started=1_000)
    _run(session, "s1", "sports", started=2_000)
    _run(session, "p2", "prediction", started=3_000)
    _event(session, "s1", "sports", "decision", "filled")

    assert [r.run_id for r in paper_runs_overview(session)] == ["p2", "s1", "p1"]
    pred = domain_paper_runs(session, "prediction")
    assert {r.run_id for r in pred} == {"p1", "p2"}
    assert all(r.domain == "prediction" for r in pred)


def test_unresolved_reconciliation_shows_as_blocking(session):
    _run(session, "p1", "prediction")
    _event(session, "p1", "prediction", "decision", "hold")
    _event(
        session,
        "p1",
        "prediction",
        "reconciliation",
        "reconciliation_required",
        asset="ETH",
        reason="orphan",
    )
    row = paper_runs_overview(session)[0]
    assert row.unresolved_reconciliation == ["ETH"]
    assert row.blocks_new_entries is True
    assert row.healthy is False


def test_ledgers_stay_domain_separated_in_the_summary(session):
    _run(session, "p1", "prediction")
    _event(session, "p1", "prediction", "decision", "hold")
    _event(session, "p1", "perp", "decision", "filled")  # stray, must not merge
    row = domain_paper_runs(session, "prediction")[0]
    assert row.decisions == 1
    assert row.fills == 0


def test_sports_area_never_renders_as_eligible_without_a_passing_report(session):
    # No discovery rows, no research report: sports is visibly not tradeable.
    areas = {a.key: a for a in market_areas(session)}
    assert areas["sports"].status in {"research", "discovered"}
    sports_admissions = [
        a for a in asset_admissions(session, now_ts=int(time.time())) if a.domain == "sports"
    ]
    # sports isn't a crypto-registry domain, so it contributes no eligible rows
    assert all(not a.eligible for a in sports_admissions)
