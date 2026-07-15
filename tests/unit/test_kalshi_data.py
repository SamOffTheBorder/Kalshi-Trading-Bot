"""Kalshi data layer: payload parsing, client retry semantics, coverage gaps."""

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kalshi_bot.data.kalshi.client import KalshiAuthError, KalshiPublicClient
from kalshi_bot.data.kalshi.coverage import coverage_report
from kalshi_bot.data.kalshi.parse import (
    dollars_to_cents,
    fp_to_int,
    iso_to_ts,
    parse_candle,
    parse_market,
)
from kalshi_bot.storage.models import Base, Candle

# --- parse ---------------------------------------------------------------

RAW_CANDLE = {
    "end_period_ts": 1784088000,
    "open_interest_fp": "1.00",
    "price": {
        "close_dollars": "0.0100",
        "high_dollars": "0.0100",
        "low_dollars": "0.0100",
        "mean_dollars": "0.0100",
        "open_dollars": "0.0100",
    },
    "volume_fp": "12.00",
    "yes_ask": {
        "close_dollars": "0.4600",
        "high_dollars": "0.4700",
        "low_dollars": "0.4500",
        "open_dollars": "0.4500",
    },
    "yes_bid": {
        "close_dollars": "0.4400",
        "high_dollars": "0.4400",
        "low_dollars": "0.4200",
        "open_dollars": "0.4200",
    },
}


def test_dollars_to_cents():
    assert dollars_to_cents("0.0100") == 1
    assert dollars_to_cents("0.4500") == 45
    assert dollars_to_cents("0.9900") == 99
    assert dollars_to_cents(None) is None
    assert dollars_to_cents("") is None


def test_fp_to_int():
    assert fp_to_int("12.00") == 12
    assert fp_to_int(None) == 0


def test_iso_to_ts():
    assert iso_to_ts("2026-07-15T04:00:00Z") == 1784088000


def test_parse_candle_real_payload():
    row = parse_candle(
        RAW_CANDLE, market_ticker="KXBTCD-X", series_ticker="KXBTCD", period_minutes=60
    )
    assert row["price_close"] == 1
    assert row["yes_ask_close"] == 46
    assert row["yes_bid_open"] == 42
    assert row["volume"] == 12
    assert row["end_period_ts"] == 1784088000


def test_parse_candle_empty_price_block():
    """No trades in period -> price dict is {} -> price fields None."""
    raw = dict(RAW_CANDLE, price={})
    row = parse_candle(raw, market_ticker="T", series_ticker="S", period_minutes=60)
    assert row["price_close"] is None
    assert row["yes_ask_close"] == 46


def test_parse_market():
    raw = {
        "ticker": "KXBTCD-26JUL1500-T72299.99",
        "event_ticker": "KXBTCD-26JUL1500",
        "title": "Bitcoin above $72,299.99?",
        "strike_type": "greater",
        "floor_strike": 72299.99,
        "cap_strike": None,
        "open_time": "2026-07-15T03:00:00Z",
        "close_time": "2026-07-15T04:00:00Z",
        "status": "settled",
        "result": "no",
    }
    row = parse_market(raw, series_ticker="KXBTCD")
    assert row["floor_strike"] == 72299.99
    assert row["result"] == "no"
    assert row["close_ts"] - row["open_ts"] == 3600


# --- client retry semantics ------------------------------------------------


def _client_with(handler) -> KalshiPublicClient:
    client = KalshiPublicClient(max_reads_per_second=1000)
    client._client = httpx.Client(base_url="https://test", transport=httpx.MockTransport(handler))
    return client


def test_client_fails_fast_on_401():
    def handler(request):
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(KalshiAuthError):
        _client_with(handler)._get("/markets")


def test_client_retries_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json={"markets": []})

    monkeypatch.setattr("time.sleep", lambda s: None)
    data = _client_with(handler)._get("/markets")
    assert data == {"markets": []}
    assert calls["n"] == 3


def test_client_gives_up_after_max_retries(monkeypatch):
    def handler(request):
        return httpx.Response(500, text="boom")

    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(httpx.HTTPStatusError):
        _client_with(handler)._get("/markets")


def test_candlestick_period_validation():
    with pytest.raises(ValueError):
        KalshiPublicClient().get_candlesticks("S", "T", start_ts=0, end_ts=1, period_minutes=5)


# --- coverage ----------------------------------------------------------------


def test_coverage_report_detects_gap():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    base_ts = 1_784_000_000
    # three consecutive hours, then a 2-hour hole, then one more
    for i, offset in enumerate([0, 3600, 7200, 18000]):
        session.add(
            Candle(
                market_ticker=f"M{i}",
                series_ticker="KXBTC",
                period_minutes=60,
                end_period_ts=base_ts + offset,
                volume=1,
                open_interest=1,
            )
        )
    session.commit()
    report = coverage_report(session, "KXBTC", 60)
    assert report.total_candles == 4
    assert report.distinct_periods == 4
    assert report.gaps == [(base_ts + 7200, base_ts + 18000)]
    assert report.first_ts == base_ts
