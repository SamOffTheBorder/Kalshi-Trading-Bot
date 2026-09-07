"""Dashboard validation-status panel (kxbtc15m-validation-rebuild §6.1):
instrument scope, data provenance, fee/resolution/calibrator versions, and
the promotion verdict must surface on the operator page, degrading cleanly
when a run has not populated them.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kalshi_bot.storage.models import BacktestRun, Base
from kalshi_bot.web.queries import latest_validation_status


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_empty_db_yields_an_all_blank_status(session):
    st = latest_validation_status(session)
    assert st.run_id is None
    assert st.instrument_scope == "—"
    assert st.promotion_status == "—"
    assert st.promotion_reasons == []


def test_validation_run_surfaces_scope_versions_and_promotion(session):
    session.add(
        BacktestRun(
            strategy_name="settlement_prob",
            params={},
            data_start_ts=1_000,
            data_end_ts=2_000,
            split_ts=1_500,
            status="completed",
            evidence_class="validation",
            fee_config_version="2026-09-kalshi",
            resolution_config_version="2026-09-kxbtc15m-brti-60s",
            provenance={"series": "KXBTC15M", "calibrator_version": "fold3-isotonic"},
            metrics_test={
                "promotion": {"passed": False, "reasons": ["only 12 trades; need 30"]},
            },
        )
    )
    session.commit()

    st = latest_validation_status(session)
    assert st.evidence_class == "validation"
    assert st.instrument_scope == "KXBTC15M only"
    assert st.fee_config_version == "2026-09-kalshi"
    assert st.resolution_config_version == "2026-09-kxbtc15m-brti-60s"
    assert st.calibrator_version == "fold3-isotonic"
    assert st.promotion_status == "failed"
    assert st.promotion_reasons == ["only 12 trades; need 30"]


def test_prefers_a_validation_run_over_a_newer_diagnostic_one(session):
    session.add(
        BacktestRun(
            strategy_name="settlement_prob", params={}, data_start_ts=1, data_end_ts=2,
            split_ts=1, status="completed", evidence_class="validation",
            provenance={"series": "KXBTC15M"},
            metrics_test={"promotion": {"passed": True, "reasons": []}},
        )
    )
    session.commit()
    session.add(
        BacktestRun(
            strategy_name="crypto_mispricing", params={}, data_start_ts=3, data_end_ts=4,
            split_ts=3, status="completed", evidence_class="diagnostic",
        )
    )
    session.commit()

    st = latest_validation_status(session)
    assert st.strategy_name == "settlement_prob"  # the validation run, not the newer diagnostic
    assert st.promotion_status == "passed"


def test_diagnostic_only_db_still_reports_that_run_as_not_evaluated(session):
    session.add(
        BacktestRun(
            strategy_name="crypto_mispricing", params={}, data_start_ts=1, data_end_ts=2,
            split_ts=1, status="completed", evidence_class="diagnostic",
        )
    )
    session.commit()
    st = latest_validation_status(session)
    assert st.evidence_class == "diagnostic"
    assert st.promotion_status == "not_evaluated"
    assert st.instrument_scope == "—"


def test_index_route_renders_the_validation_panel(monkeypatch, tmp_path):
    """Smoke test: the index page renders with the new panel present."""
    db = tmp_path / "dash.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("KALSHI_KEY_ID", "test-key")

    from fastapi.testclient import TestClient

    from kalshi_bot.web.app import create_app

    client = TestClient(create_app())
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Validation status" in resp.text
    assert "Promotion" in resp.text
