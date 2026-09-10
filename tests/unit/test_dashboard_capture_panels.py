"""Dashboard capture-health and validation-readiness panels.

These panels exist to make the project's binding constraint visible: a dead
capture feed, and how far the BRTI window is from supporting a verdict. The
numbers must be measured from the archive, never estimated, so the tests
assert against a hand-built archive with known answers.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kalshi_bot.storage import BRTIObservation, KalshiMarket, PerpMarkObservation
from kalshi_bot.storage.db import create_all_tables
from kalshi_bot.web import queries

BTC = queries.BTC_INDEX_SOURCE
DAY = 86_400


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    return sessionmaker(bind=engine)


def _brti(session, *, start: int, count: int, step: int, source: str = BTC) -> None:
    for i in range(count):
        ts = start + i * step
        session.add(
            BRTIObservation(
                observed_at=ts,
                available_at=ts,
                value_dollars="100000.00",
                source=source,
            )
        )
    session.commit()


def _market(session, ticker: str, close_ts: int) -> None:
    session.add(
        KalshiMarket(
            ticker=ticker,
            series_ticker="KXBTC15M",
            open_ts=close_ts - 900,
            close_ts=close_ts,
            status="settled",
        )
    )


# ----------------------------------------------------------------- feeds


def test_feed_reports_live_when_recently_observed(session_factory):
    now = int(time.time())
    with session_factory() as s:
        _brti(s, start=now - 600, count=10, step=60)
        feeds = {f.name: f for f in queries.capture_feeds(s)}

    btc = feeds["BRTI (Bitcoin index)"]
    assert btc.rows == 10
    assert btc.status == "live"
    assert btc.age_s is not None and btc.age_s < 120


def test_feed_reports_stale_after_long_silence(session_factory):
    now = int(time.time())
    with session_factory() as s:
        # Last reading is far beyond the stale threshold (20 x 60s).
        _brti(s, start=now - 10 * 3600, count=5, step=60)
        feeds = {f.name: f for f in queries.capture_feeds(s)}

    assert feeds["BRTI (Bitcoin index)"].status == "stale"


def test_empty_feed_reports_empty_not_crash(session_factory):
    with session_factory() as s:
        feeds = {f.name: f for f in queries.capture_feeds(s)}

    btc = feeds["BRTI (Bitcoin index)"]
    assert btc.rows == 0
    assert btc.status == "empty"
    assert btc.age_s is None
    assert btc.span_hours == 0.0


def test_btc_feed_excludes_other_indices(session_factory):
    """A multi-index archive must not count ETH rows toward BTC readiness —
    the backtest engine filters the same way."""
    now = int(time.time())
    with session_factory() as s:
        _brti(s, start=now - 300, count=5, step=60)
        _brti(s, start=now - 300, count=50, step=60, source="kalshi:cfbenchmarks/ETHUSD_RTI")
        feeds = {f.name: f for f in queries.capture_feeds(s)}

    assert feeds["BRTI (Bitcoin index)"].rows == 5
    assert feeds["Other CF indices"].rows == 50


def test_perp_marks_tracked_separately(session_factory):
    now = int(time.time())
    with session_factory() as s:
        s.add(
            PerpMarkObservation(
                market_ticker="KXBTCPERP",
                observed_at=now - 30,
                available_at=now - 30,
                settlement_mark_dollars="7.92",
                source="kalshi:margin/markets",
            )
        )
        s.commit()
        feeds = {f.name: f for f in queries.capture_feeds(s)}

    assert feeds["Perp marks"].rows == 1
    assert feeds["Perp marks"].status == "live"


# ------------------------------------------------------------- readiness


def _readiness(session):
    return queries.validation_readiness(
        session,
        train_seconds=28 * DAY,
        test_seconds=14 * DAY,
        embargo_seconds=DAY,
        min_folds=3,
    )


def test_readiness_requires_full_fold_geometry(session_factory):
    """28 train + 1 embargo + 3 x 14 test = 71 days."""
    with session_factory() as s:
        r = _readiness(s)
    assert r.required_days == pytest.approx(71.0)


def test_short_window_is_not_ready_and_reports_remaining(session_factory):
    now = int(time.time())
    with session_factory() as s:
        _brti(s, start=now - 2 * DAY, count=200, step=864)  # exactly 2 days span
        r = _readiness(s)

    assert not r.is_ready
    assert r.brti_span_days == pytest.approx(2.0, abs=0.05)
    assert r.days_remaining == pytest.approx(69.0, abs=0.05)
    assert 0 < r.pct_complete < 5
    assert r.projected_ready_ts is not None


def test_sufficient_window_is_ready(session_factory):
    now = int(time.time())
    with session_factory() as s:
        _brti(s, start=now - 80 * DAY, count=100, step=80 * DAY // 99)
        r = _readiness(s)

    assert r.is_ready
    assert r.pct_complete == 100.0
    assert r.days_remaining == 0
    assert r.projected_ready_ts is None


def test_overlap_counts_only_markets_inside_the_brti_window(session_factory):
    """The zero-trade diagnosis: markets outside the captured index window
    cannot be evaluated, so they must not be counted as ready."""
    now = int(time.time())
    with session_factory() as s:
        _brti(s, start=now - DAY, count=100, step=864)  # BRTI covers last 1 day
        _market(s, "KXBTC15M-IN-1", now - DAY // 2)  # inside
        _market(s, "KXBTC15M-IN-2", now - DAY // 4)  # inside
        _market(s, "KXBTC15M-OLD-1", now - 40 * DAY)  # long before capture
        _market(s, "KXBTC15M-OLD-2", now - 30 * DAY)  # long before capture
        s.commit()
        r = _readiness(s)

    assert r.markets_in_overlap == 2
    assert r.overlap_days < 1.1


def test_no_overlap_when_brti_and_markets_are_disjoint(session_factory):
    now = int(time.time())
    with session_factory() as s:
        _brti(s, start=now - DAY, count=50, step=1728)
        _market(s, "KXBTC15M-OLD", now - 60 * DAY)
        s.commit()
        r = _readiness(s)

    assert r.markets_in_overlap == 0
    assert r.overlap_days == 0.0


# -------------------------------------------------------------- sampling


def test_sampling_detects_one_sample_per_settlement_window(session_factory):
    """A 60s poll collapses the 60s settlement average to a single reading."""
    now = int(time.time())
    with session_factory() as s:
        _brti(s, start=now - 3600, count=60, step=60)
        q = queries.sampling_quality(s)

    assert q.median_gap_s == 60
    assert q.mean_per_window == pytest.approx(1.0)
    assert q.long_gaps == 0


def test_sampling_detects_dense_polling(session_factory):
    now = int(time.time())
    with session_factory() as s:
        _brti(s, start=now - 600, count=120, step=5)
        q = queries.sampling_quality(s)

    assert q.median_gap_s == 5
    assert q.mean_per_window > 5


def test_sampling_counts_long_gaps(session_factory):
    now = int(time.time())
    with session_factory() as s:
        _brti(s, start=now - 7200, count=10, step=60)
        _brti(s, start=now - 1800, count=10, step=60)  # ~an hour of silence
        q = queries.sampling_quality(s)

    assert q.long_gaps == 1


def test_sampling_on_empty_archive(session_factory):
    with session_factory() as s:
        q = queries.sampling_quality(s)
    assert q.median_gap_s is None
    assert q.mean_per_window == 0.0


# ----------------------------------------------------------------- routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "dash.db"))
    monkeypatch.setenv("KALSHI_KEY_ID", "test-key")
    from kalshi_bot.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    from kalshi_bot.web.app import create_app

    yield TestClient(create_app())
    settings_mod.get_settings.cache_clear()


def test_overview_renders_capture_and_readiness_panels(client):
    body = client.get("/").text
    assert "Validation readiness" in body
    assert "Capture feeds" in body
    assert "BRTI (Bitcoin index)" in body


def test_data_page_renders(client):
    body = client.get("/data").text
    assert "Sampling resolution" in body
    assert "Contract archive coverage" in body


def test_market_sections_are_first_class_routes(client):
    body = client.get("/markets").text
    assert "Sports betting" in body
    assert "Perpetuals" in body
    assert "Prediction markets" in body
    assert client.get("/sports").status_code == 200
    assert client.get("/perps").status_code == 200
    assert client.get("/prediction-markets").status_code == 200


def test_overview_and_areas_show_paper_run_health_panels(client):
    assert "Paper &amp; shadow runs — all domains" in client.get("/").text
    for path in ("/sports", "/perps", "/prediction-markets"):
        assert "Paper &amp; shadow runs" in client.get(path).text
    # Per-asset admission is BTC/ETH/SOL/XRP — the crypto domains only.
    for path in ("/perps", "/prediction-markets"):
        assert "Per-asset admission" in client.get(path).text
    assert "Per-asset admission" not in client.get("/sports").text


def test_controls_redirect_and_toggle_state(client):
    assert client.post("/control/kill", follow_redirects=False).status_code == 303
    assert "STOPPED" in client.get("/").text
    client.post("/control/arm", follow_redirects=False)
    assert "ARMED" in client.get("/").text


def test_dashboard_has_no_external_script_dependency(client):
    """The kill switch must work with no network and no CDN reachable."""
    body = client.get("/").text
    assert "unpkg.com" not in body
    assert "<script" not in body
