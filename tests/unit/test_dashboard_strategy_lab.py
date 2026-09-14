"""Dashboard strategy-lab queries (strategy-lab-multi-account §7.6).

Covers: `PaperRunSummary` carries `strategy_id` + `strategy_gate_status`
and a `decisions_without_fills` flag; `strategy_lab_comparison` lists runs
side by side keyed by run id; `perp_positions_view` reports a position's
bracket, funding, and liquidation distance; the `/strategy-lab` route
renders.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from kalshi_bot.storage import (  # noqa: E402
    Base,
    PaperAuditEvent,
    PaperRun,
    PerpPaperEvent,
    PerpPaperPosition,
)
from kalshi_bot.web.queries import (  # noqa: E402
    paper_runs_overview,
    perp_positions_view,
    strategy_lab_comparison,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _run(session, run_id, *, domain="prediction", strategy_id="trend_scalp",
         gate="gate_failed", started=1_000):
    session.add(
        PaperRun(
            id=run_id, domain=domain, mode="paper", asset_ids=["BTC"],
            started_at=started, ended_at=started + 100, status="completed",
            config_fingerprint="x",
            strategy_id=strategy_id, strategy_config_version=f"{strategy_id}-v1",
            strategy_gate_status=gate,
        )
    )
    session.commit()


def _preflight_event(session, run_id, *, admissions, started=1_005):
    session.add(
        PaperAuditEvent(
            paper_run_id=run_id, kind="run", domain="prediction",
            observed_at=started, status="preflight_passed",
            payload={"admissions": admissions},
        )
    )
    session.commit()


def _decision_events(session, run_id, n, *, started=1_010):
    for i in range(n):
        session.add(
            PaperAuditEvent(
                paper_run_id=run_id, kind="decision", domain="prediction",
                asset_id="BTC", observed_at=started + i, status="hold",
                reason="no_edge", payload={"action": "hold"},
            )
        )
    session.commit()


# -- summary fields --------------------------------------------------


def test_summary_carries_strategy_id_and_gate_status(session):
    _run(session, "run-1", strategy_id="level_break", gate="gate_failed")
    summaries = paper_runs_overview(session)
    assert len(summaries) == 1
    assert summaries[0].strategy_id == "level_break"
    assert summaries[0].strategy_gate_status == "gate_failed"


def test_summary_gate_status_is_none_for_a_pre_v14_run(session):
    session.add(
        PaperRun(
            id="old", domain="prediction", mode="paper", asset_ids=["BTC"],
            started_at=1, status="completed", config_fingerprint="x",
        )
    )
    session.commit()
    summaries = paper_runs_overview(session)
    assert summaries[0].strategy_id is None
    assert summaries[0].strategy_gate_status is None


def test_decisions_without_fills_flag(session):
    _run(session, "run-2")
    _preflight_event(
        session, "run-2",
        admissions=[
            {"asset": "BTC", "lifecycle": "paper", "admitted": True,
             "may_fill": False, "reason": "reconstructed_data_not_admissible"},
        ],
    )
    _decision_events(session, "run-2", 3)
    summary = paper_runs_overview(session)[0]
    assert summary.decisions == 3
    assert summary.fills == 0
    assert summary.decisions_without_fills is True
    assert "BTC" in summary.blocked_fill_reasons


def test_decisions_without_fills_false_when_nothing_blocked(session):
    _run(session, "run-3")
    _decision_events(session, "run-3", 2)
    summary = paper_runs_overview(session)[0]
    assert summary.decisions_without_fills is False


# -- comparison view ----------------------------------------------


def test_comparison_lists_runs_keyed_by_run_id(session):
    _run(session, "run-a", strategy_id="trend_scalp", gate="gate_failed")
    _run(session, "run-b", strategy_id="settlement_prob", gate="never_gated",
         started=2_000)
    rows = strategy_lab_comparison(session)
    by_id = {r.run_id: r for r in rows}
    assert by_id["run-a"].strategy_gate_status == "gate_failed"
    assert by_id["run-b"].strategy_gate_status == "never_gated"
    assert by_id["run-a"].strategy_id == "trend_scalp"


def test_comparison_surfaces_decisions_without_fills(session):
    _run(session, "run-c")
    _preflight_event(
        session, "run-c",
        admissions=[
            {"asset": "BTC", "lifecycle": "paper", "admitted": True,
             "may_fill": False, "reason": "no_frozen_admission_report"},
        ],
    )
    _decision_events(session, "run-c", 4)
    row = next(r for r in strategy_lab_comparison(session) if r.run_id == "run-c")
    assert row.decisions_without_fills is True
    assert row.blocked_fill_reasons["BTC"] == "no_frozen_admission_report"


# -- perp positions view ----------------------------------------


def test_perp_positions_view_reports_bracket_and_liquidation_distance(session):
    session.add(
        PaperRun(
            id="perp-run", domain="perp", mode="paper", asset_ids=["BTC"],
            started_at=1, status="running", config_fingerprint="x",
        )
    )
    session.flush()
    pos = PerpPaperPosition(
        paper_run_id="perp-run", asset_id="BTC", market_ticker="KXBTCPERP",
        signed_quantity=1.0, multiplier=1.0, entry_price=100.0, entry_ts=10,
        funding_pnl_usd=-0.5, fee_usd=0.1,
    )
    session.add(pos)
    session.flush()
    session.add(
        PerpPaperEvent(
            position_id=pos.id, paper_run_id="perp-run", event_type="fill",
            observed_at=10, price=100.0, quantity=1.0,
            liquidation_price=80.0, status="filled",
            payload={"bracket": {"stop_loss": 90.0, "take_profit": 120.0}},
        )
    )
    session.add(
        PerpPaperEvent(
            position_id=pos.id, paper_run_id="perp-run", event_type="mark",
            observed_at=20, price=104.0, status="observed",
        )
    )
    session.commit()

    views = perp_positions_view(session)
    assert len(views) == 1
    v = views[0]
    assert v.stop_loss == 90.0
    assert v.take_profit == 120.0
    assert v.latest_mark == 104.0
    assert v.funding_pnl_usd == -0.5
    # long: (mark - liq) / mark = (104 - 80) / 104
    assert v.liquidation_distance_pct == pytest.approx((104.0 - 80.0) / 104.0)


def test_perp_positions_view_empty_when_none(session):
    assert perp_positions_view(session) == []


# -- route --------------------------------------------------------


def test_strategy_lab_route_renders(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    monkeypatch.setenv("DB_PATH", str(tmp_path / "dash.db"))
    monkeypatch.setenv("KALSHI_KEY_ID", "test-key")
    from kalshi_bot.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    from kalshi_bot.storage.db import create_all_tables, get_engine, get_session_factory
    from kalshi_bot.web.app import create_app

    engine = get_engine(settings_mod.get_settings())
    create_all_tables(engine)
    with get_session_factory(engine)() as session:
        _run(session, "run-x", strategy_id="trend_scalp", gate="gate_failed")

    try:
        client = TestClient(create_app())
        resp = client.get("/strategy-lab")
        assert resp.status_code == 200
        assert "Strategy lab" in resp.text
        assert "gate failed" in resp.text
        assert "no backtest mode" in resp.text
    finally:
        settings_mod.get_settings.cache_clear()
