"""No-unbracketed-position invariant (tasks.md 5.2, design D4, spec: perps-trading).

Uses a real KalshiMarginClient with mocked HTTP (httpx.MockTransport) — no
live call is made against demo or production.
"""

from __future__ import annotations

import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from kalshi_bot.execution.kalshi_margin_client import KalshiMarginClient
from kalshi_bot.risk.exit_triggers import attach_mandatory_bracket


@pytest.fixture
def private_key_path(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path = tmp_path / "key.pem"
    path.write_bytes(pem)
    return path


def _client_with(private_key_path, handler) -> KalshiMarginClient:
    client = KalshiMarginClient(
        key_id="test-key-id",
        private_key_path=private_key_path,
        use_demo_env=True,
        max_reads_per_second=1000,
    )
    client._client = httpx.Client(base_url="https://test", transport=httpx.MockTransport(handler))
    return client


def test_bracket_attached_successfully_reports_ok(private_key_path):
    def handler(request):
        assert request.method == "PUT"
        return httpx.Response(200, json={"id": "t1", "status": "active"})

    client = _client_with(private_key_path, handler)
    result = attach_mandatory_bracket(
        client,
        ticker="KXBTCPERP",
        position_kind="isolated",
        stop_loss_price="49000.00",
        take_profit_price="52000.00",
        close_side="ask",
        close_count="1",
        marketable_close_price="0.01",
    )
    assert result.ok is True
    assert result.closed_due_to_failure is False
    assert result.exit_trigger is not None
    assert result.exit_trigger["id"] == "t1"


def test_bracket_attach_failure_closes_position_immediately(private_key_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "PUT":
            return httpx.Response(500, text="exit trigger service down")
        return httpx.Response(200, json={"order_id": "close-1", "status": "executed"})

    client = _client_with(private_key_path, handler)
    result = attach_mandatory_bracket(
        client,
        ticker="KXBTCPERP",
        position_kind="isolated",
        stop_loss_price="49000.00",
        close_side="ask",
        close_count="1",
        marketable_close_price="0.01",
    )
    assert result.ok is False
    assert result.closed_due_to_failure is True
    assert result.error is not None
    # A closing order was actually submitted, not merely logged.
    assert ("POST", "/margin/orders") in calls


def test_closing_order_is_reduce_only_and_immediate(private_key_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    seen_body = {}

    def handler(request):
        if request.method == "PUT":
            return httpx.Response(500, text="down")
        seen_body.update(json.loads(request.content))
        return httpx.Response(200, json={"order_id": "close-1", "status": "executed"})

    client = _client_with(private_key_path, handler)
    attach_mandatory_bracket(
        client,
        ticker="KXBTCPERP",
        position_kind="cross",
        stop_loss_price="49000.00",
        close_side="bid",
        close_count="3",
        marketable_close_price="99999.00",
    )
    assert seen_body["reduce_only"] is True
    assert seen_body["time_in_force"] == "immediate_or_cancel"
    assert seen_body["post_only"] is False
    assert seen_body["side"] == "bid"
    assert seen_body["count"] == "3"
    assert seen_body["price"] == "99999.00"


def test_unconfirmed_emergency_close_stays_closing(private_key_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    def handler(request):
        if request.method == "PUT":
            return httpx.Response(500, text="down")
        return httpx.Response(200, json={"order_id": "close-1", "status": "resting"})

    client = _client_with(private_key_path, handler)
    result = attach_mandatory_bracket(
        client,
        ticker="KXBTCPERP",
        position_kind="isolated",
        stop_loss_price="49000.00",
        close_side="ask",
        close_count="1",
        marketable_close_price="0.01",
    )
    assert result.ok is False
    assert result.closed_due_to_failure is False
    assert result.error is not None and "close_unconfirmed" in result.error

def test_both_bracket_and_close_failing_reports_not_closed(private_key_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    def handler(request):
        return httpx.Response(500, text="everything is down")

    client = _client_with(private_key_path, handler)
    result = attach_mandatory_bracket(
        client,
        ticker="KXBTCPERP",
        position_kind="isolated",
        stop_loss_price="49000.00",
        close_side="ask",
        close_count="1",
        marketable_close_price="0.01",
    )
    assert result.ok is False
    assert result.closed_due_to_failure is False
    assert result.error is not None
    assert "bracket_error" in result.error
    assert "close_error" in result.error


def test_cross_position_uses_cross_exit_trigger_endpoint(private_key_path):
    seen_path = {}

    def handler(request):
        if request.method == "PUT":
            seen_path["path"] = request.url.path
            return httpx.Response(200, json={"id": "t1"})
        return httpx.Response(200, json={})

    client = _client_with(private_key_path, handler)
    attach_mandatory_bracket(
        client,
        ticker="KXBTCPERP",
        position_kind="cross",
        stop_loss_price="49000.00",
        close_side="ask",
        close_count="1",
        marketable_close_price="0.01",
    )
    assert seen_path["path"] == "/margin/cross/positions/KXBTCPERP/exit_trigger"


def test_isolated_position_uses_isolated_exit_trigger_endpoint(private_key_path):
    seen_path = {}

    def handler(request):
        if request.method == "PUT":
            seen_path["path"] = request.url.path
            return httpx.Response(200, json={"id": "t1"})
        return httpx.Response(200, json={})

    client = _client_with(private_key_path, handler)
    attach_mandatory_bracket(
        client,
        ticker="KXBTCPERP",
        position_kind="isolated",
        stop_loss_price="49000.00",
        close_side="ask",
        close_count="1",
        marketable_close_price="0.01",
    )
    assert seen_path["path"] == "/margin/isolated/positions/KXBTCPERP/exit_trigger"
