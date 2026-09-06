"""Kalshi margin (perps) client: read-only endpoints and order placement.

All HTTP is mocked — no live call is made against demo or production here.
"""

from __future__ import annotations

import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from kalshi_bot.execution.kalshi_client import (
    LIVE_TRADING_CONFIRMATION_PHRASE,
    KalshiAuthError,
    KalshiConfigError,
)
from kalshi_bot.execution.kalshi_margin_client import KalshiMarginClient


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


def _client_with(private_key_path, handler, **kwargs) -> KalshiMarginClient:
    client = KalshiMarginClient(
        key_id="test-key-id",
        private_key_path=private_key_path,
        use_demo_env=True,
        max_reads_per_second=1000,
        **kwargs,
    )
    client._client = httpx.Client(base_url="https://test", transport=httpx.MockTransport(handler))
    return client


def test_get_markets_hits_expected_path(private_key_path):
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"markets": []})

    client = _client_with(private_key_path, handler)
    client.get_markets(status="active")
    assert seen["path"] == "/margin/markets"
    assert seen["params"]["status"] == "active"


def test_get_market_orderbook_path_includes_ticker(private_key_path):
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(200, json={"orderbook": {"bids": [], "asks": []}})

    client = _client_with(private_key_path, handler)
    client.get_market_orderbook("KXBTCPERP")
    assert seen["path"] == "/margin/markets/KXBTCPERP/orderbook"


def test_get_positions_passes_filters(private_key_path):
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"positions": []})

    client = _client_with(private_key_path, handler)
    client.get_positions(subaccount=1, ticker="KXBTCPERP")
    assert seen["params"]["subaccount"] == "1"
    assert seen["params"]["ticker"] == "KXBTCPERP"


def test_get_balance_omits_flag_by_default(private_key_path):
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"subaccount_balances": []})

    client = _client_with(private_key_path, handler)
    client.get_balance()
    assert "compute_available_balance" not in seen["params"]


def test_get_risk_hits_expected_path(private_key_path):
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(200, json={"account_leverage": 1.5, "positions": []})

    client = _client_with(private_key_path, handler)
    data = client.get_risk()
    assert seen["path"] == "/margin/risk"
    assert data["account_leverage"] == 1.5


def test_get_funding_rate_estimate_requires_ticker_param(private_key_path):
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"funding_rate": 0.0001})

    client = _client_with(private_key_path, handler)
    client.get_funding_rate_estimate("KXBTCPERP")
    assert seen["params"]["ticker"] == "KXBTCPERP"


def test_get_historical_funding_rates_passes_time_range(private_key_path):
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"funding_rates": []})

    client = _client_with(private_key_path, handler)
    client.get_historical_funding_rates(ticker="KXBTCPERP", start_ts=100, end_ts=200)
    assert seen["params"]["start_ts"] == "100"
    assert seen["params"]["end_ts"] == "200"


def test_fails_fast_on_401(private_key_path):
    def handler(request):
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(KalshiAuthError):
        _client_with(private_key_path, handler).get_positions()


def test_retries_429_then_succeeds(private_key_path, monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json={"positions": []})

    monkeypatch.setattr("time.sleep", lambda s: None)
    data = _client_with(private_key_path, handler).get_positions()
    assert data == {"positions": []}
    assert calls["n"] == 3


def test_create_order_defaults_to_post_only(private_key_path):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"order_id": "m1"})

    client = _client_with(private_key_path, handler)
    client.create_order(market_ticker="KXBTCPERP", side="bid", count="1", price="50000.00")
    assert seen["body"]["post_only"] is True
    assert seen["body"]["ticker"] == "KXBTCPERP"
    assert seen["body"]["client_order_id"]


def test_create_order_refuses_prod_while_paper_trading(private_key_path):
    client = KalshiMarginClient(
        key_id="k",
        private_key_path=private_key_path,
        use_demo_env=False,
        paper_trading=True,
    )
    client._client = httpx.Client(
        base_url="https://test",
        transport=httpx.MockTransport(lambda r: pytest.fail("no request should be made")),
    )
    with pytest.raises(KalshiConfigError):
        client.create_order(market_ticker="KXBTCPERP", side="bid", count="1", price="50000.00")
    client.close()


def test_create_order_refuses_prod_when_paper_trading_false_without_phrase(private_key_path):
    client = KalshiMarginClient(
        key_id="k", private_key_path=private_key_path, use_demo_env=False, paper_trading=False
    )
    client._client = httpx.Client(
        base_url="https://test",
        transport=httpx.MockTransport(lambda r: pytest.fail("no request should be made")),
    )
    with pytest.raises(KalshiConfigError):
        client.create_order(market_ticker="KXBTCPERP", side="bid", count="1", price="50000.00")
    client.close()


def test_create_order_allowed_on_prod_when_paper_trading_false_and_phrase_matches(
    private_key_path,
):
    def handler(request):
        return httpx.Response(200, json={"order_id": "m1"})

    client = KalshiMarginClient(
        key_id="k",
        private_key_path=private_key_path,
        use_demo_env=False,
        paper_trading=False,
        live_trading_confirmation_phrase=LIVE_TRADING_CONFIRMATION_PHRASE,
        max_reads_per_second=1000,
    )
    client._client = httpx.Client(base_url="https://test", transport=httpx.MockTransport(handler))
    result = client.create_order(market_ticker="KXBTCPERP", side="bid", count="1", price="50000.00")
    assert result["order_id"] == "m1"
    client.close()


# --- exit triggers (tasks.md 4.5) — mocked HTTP only, no live calls --------


def test_get_isolated_exit_triggers_hits_expected_path(private_key_path):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"exit_triggers": []})

    client = _client_with(private_key_path, handler)
    client.get_isolated_exit_triggers("KXBTCPERP", kind="bracket")
    assert seen["method"] == "GET"
    assert seen["path"] == "/margin/isolated/positions/KXBTCPERP/exit_trigger"
    assert seen["params"]["kind"] == "bracket"


def test_set_isolated_exit_trigger_sends_put_with_bracket_legs(private_key_path):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "t1", "kind": "bracket", "status": "active"})

    client = _client_with(private_key_path, handler)
    client.set_isolated_exit_trigger(
        "KXBTCPERP", stop_loss_price="49000.00", take_profit_price="52000.00"
    )
    assert seen["method"] == "PUT"
    assert seen["path"] == "/margin/isolated/positions/KXBTCPERP/exit_trigger"
    assert seen["body"]["kind"] == "bracket"
    assert seen["body"]["stop_loss_price"] == "49000.00"
    assert seen["body"]["take_profit_price"] == "52000.00"


def test_set_isolated_exit_trigger_trailing(private_key_path):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "t1", "kind": "trailing", "status": "active"})

    client = _client_with(private_key_path, handler)
    client.set_isolated_exit_trigger("KXBTCPERP", kind="trailing", trail_bps=250)
    assert seen["body"]["kind"] == "trailing"
    assert seen["body"]["trail_bps"] == 250
    assert "stop_loss_price" not in seen["body"]


def test_set_isolated_exit_trigger_refuses_prod_while_paper_trading(private_key_path):
    client = KalshiMarginClient(
        key_id="k", private_key_path=private_key_path, use_demo_env=False, paper_trading=True
    )
    client._client = httpx.Client(
        base_url="https://test",
        transport=httpx.MockTransport(lambda r: pytest.fail("no request should be made")),
    )
    with pytest.raises(KalshiConfigError):
        client.set_isolated_exit_trigger("KXBTCPERP", stop_loss_price="49000.00")
    client.close()


def test_cancel_isolated_exit_trigger_sends_delete(private_key_path):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={})

    client = _client_with(private_key_path, handler)
    client.cancel_isolated_exit_trigger("KXBTCPERP", kind="trailing")
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/margin/isolated/positions/KXBTCPERP/exit_trigger"
    assert seen["params"]["kind"] == "trailing"


def test_get_cross_exit_triggers_passes_subaccount(private_key_path):
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"exit_triggers": []})

    client = _client_with(private_key_path, handler)
    client.get_cross_exit_triggers("KXBTCPERP", subaccount=1)
    assert seen["path"] == "/margin/cross/positions/KXBTCPERP/exit_trigger"
    assert seen["params"]["subaccount"] == "1"


def test_set_cross_exit_trigger_whole_position(private_key_path):
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "t1", "kind": "bracket", "status": "active"})

    client = _client_with(private_key_path, handler)
    client.set_cross_exit_trigger("KXBTCPERP", stop_loss_price="49000.00")
    assert seen["path"] == "/margin/cross/positions/KXBTCPERP/exit_trigger"
    assert seen["body"]["stop_loss_price"] == "49000.00"
    assert "client_trigger_id" not in seen["body"]


def test_set_cross_exit_trigger_partial_requires_client_trigger_id(private_key_path):
    client = _client_with(private_key_path, lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        client.set_cross_exit_trigger("KXBTCPERP", count="1", stop_loss_price="49000.00")


def test_set_cross_exit_trigger_partial_with_client_trigger_id(private_key_path):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "t1", "kind": "bracket", "status": "active"})

    client = _client_with(private_key_path, handler)
    client.set_cross_exit_trigger(
        "KXBTCPERP",
        count="1",
        client_trigger_id="my-bracket-1",
        take_profit_price="52000.00",
    )
    assert seen["body"]["count"] == "1"
    assert seen["body"]["client_trigger_id"] == "my-bracket-1"


def test_update_cross_exit_trigger_sends_put_to_trigger_id(private_key_path):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "t1"})

    client = _client_with(private_key_path, handler)
    client.update_cross_exit_trigger("KXBTCPERP", "t1", stop_loss_price="48000.00")
    assert seen["method"] == "PUT"
    assert seen["path"] == "/margin/cross/positions/KXBTCPERP/exit_trigger/t1"
    assert seen["body"] == {"stop_loss_price": "48000.00"}


def test_update_cross_exit_trigger_requires_a_leg(private_key_path):
    client = _client_with(private_key_path, lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        client.update_cross_exit_trigger("KXBTCPERP", "t1")


def test_cancel_cross_exit_triggers_sends_delete(private_key_path):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(200, json={})

    client = _client_with(private_key_path, handler)
    client.cancel_cross_exit_triggers("KXBTCPERP")
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/margin/cross/positions/KXBTCPERP/exit_trigger"


def test_cancel_cross_exit_trigger_by_id_sends_delete_with_id(private_key_path):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(204)

    client = _client_with(private_key_path, handler)
    client.cancel_cross_exit_trigger_by_id("KXBTCPERP", "t1")
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/margin/cross/positions/KXBTCPERP/exit_trigger/t1"


def test_set_isolated_exit_trigger_refuses_prod_when_paper_trading_false_without_phrase(
    private_key_path,
):
    client = KalshiMarginClient(
        key_id="k", private_key_path=private_key_path, use_demo_env=False, paper_trading=False
    )
    client._client = httpx.Client(
        base_url="https://test",
        transport=httpx.MockTransport(lambda r: pytest.fail("no request should be made")),
    )
    with pytest.raises(KalshiConfigError):
        client.set_isolated_exit_trigger("KXBTCPERP", stop_loss_price="49000.00")
    client.close()


def test_set_isolated_exit_trigger_allowed_with_correct_phrase(private_key_path):
    def handler(request):
        return httpx.Response(200, json={"id": "t1"})

    client = KalshiMarginClient(
        key_id="k",
        private_key_path=private_key_path,
        use_demo_env=False,
        paper_trading=False,
        live_trading_confirmation_phrase=LIVE_TRADING_CONFIRMATION_PHRASE,
        max_reads_per_second=1000,
    )
    client._client = httpx.Client(base_url="https://test", transport=httpx.MockTransport(handler))
    result = client.set_isolated_exit_trigger("KXBTCPERP", stop_loss_price="49000.00")
    assert result["id"] == "t1"
    client.close()


def test_cancel_cross_exit_trigger_by_id_refuses_prod_while_paper_trading(private_key_path):
    client = KalshiMarginClient(
        key_id="k", private_key_path=private_key_path, use_demo_env=False, paper_trading=True
    )
    client._client = httpx.Client(
        base_url="https://test",
        transport=httpx.MockTransport(lambda r: pytest.fail("no request should be made")),
    )
    with pytest.raises(KalshiConfigError):
        client.cancel_cross_exit_trigger_by_id("KXBTCPERP", "t1")
    client.close()
