"""Funding-rate awareness (tasks.md 5.5, spec: perps-trading "Funding-rate
awareness"). Sign convention is a documented assumption — see
funding_awareness.py's module docstring."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kalshi_bot.risk.funding_awareness import funding_state_from_estimate


def _estimate_response(**overrides) -> dict:
    base = {
        "market_ticker": "KXBTCPERP",
        "computed_time": "2026-09-06T12:00:00Z",
        "funding_rate": 0.0001,
        "mark_price": "50000.00",
        "next_funding_time": "2026-09-06T16:00:00Z",
    }
    base.update(overrides)
    return base


def test_next_funding_time_and_rate_are_retrievable():
    state = funding_state_from_estimate(
        _estimate_response(), side="long", position_notional_usd=10_000.0
    )
    assert state.market_ticker == "KXBTCPERP"
    assert state.funding_rate == pytest.approx(0.0001)
    assert state.mark_price == pytest.approx(50000.00)
    assert state.next_funding_time == datetime(2026, 9, 6, 16, 0, 0, tzinfo=UTC)


def test_long_pays_when_funding_rate_positive():
    state = funding_state_from_estimate(
        _estimate_response(funding_rate=0.0002), side="long", position_notional_usd=10_000.0
    )
    assert state.pays_or_receives == "pays"
    assert state.estimated_payment_usd == pytest.approx(2.0)


def test_short_receives_when_funding_rate_positive():
    state = funding_state_from_estimate(
        _estimate_response(funding_rate=0.0002), side="short", position_notional_usd=10_000.0
    )
    assert state.pays_or_receives == "receives"
    assert state.estimated_payment_usd == pytest.approx(-2.0)


def test_long_receives_when_funding_rate_negative():
    state = funding_state_from_estimate(
        _estimate_response(funding_rate=-0.0002), side="long", position_notional_usd=10_000.0
    )
    assert state.pays_or_receives == "receives"
    assert state.estimated_payment_usd == pytest.approx(-2.0)


def test_short_pays_when_funding_rate_negative():
    state = funding_state_from_estimate(
        _estimate_response(funding_rate=-0.0002), side="short", position_notional_usd=10_000.0
    )
    assert state.pays_or_receives == "pays"
    assert state.estimated_payment_usd == pytest.approx(2.0)


def test_zero_funding_rate_is_flat():
    state = funding_state_from_estimate(
        _estimate_response(funding_rate=0.0), side="long", position_notional_usd=10_000.0
    )
    assert state.pays_or_receives == "flat"
    assert state.estimated_payment_usd == 0.0
