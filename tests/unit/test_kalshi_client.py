"""Authenticated Kalshi client: RSA-PSS signing and read-only endpoints."""

from __future__ import annotations

import base64

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from kalshi_bot.execution.kalshi_client import (
    DEMO_BASE_URL,
    LIVE_TRADING_CONFIRMATION_PHRASE,
    PROD_BASE_URL,
    KalshiAuthenticatedClient,
    KalshiAuthError,
    KalshiConfigError,
    sign_request,
)


@pytest.fixture
def key_pair(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path = tmp_path / "key.pem"
    path.write_bytes(pem)
    return path, key


@pytest.fixture
def private_key_path(key_pair):
    path, _key = key_pair
    return path


def _client_with(private_key_path, handler) -> KalshiAuthenticatedClient:
    client = KalshiAuthenticatedClient(
        key_id="test-key-id",
        private_key_path=private_key_path,
        use_demo_env=True,
        max_reads_per_second=1000,
    )
    client._client = httpx.Client(base_url="https://test", transport=httpx.MockTransport(handler))
    return client


def test_demo_env_selects_demo_base_url(private_key_path):
    client = KalshiAuthenticatedClient(
        key_id="k", private_key_path=private_key_path, use_demo_env=True
    )
    assert client._base_url == DEMO_BASE_URL
    client.close()


def test_prod_env_selects_prod_base_url(private_key_path):
    client = KalshiAuthenticatedClient(
        key_id="k", private_key_path=private_key_path, use_demo_env=False
    )
    assert client._base_url == PROD_BASE_URL
    client.close()


def test_sign_request_is_verifiable(key_pair):
    _path, key = key_pair
    public_key = key.public_key()
    signature_b64 = sign_request(key, "1700000000000", "GET", "/trade-api/v2/portfolio/balance")
    signature = base64.b64decode(signature_b64)
    message = b"1700000000000GET/trade-api/v2/portfolio/balance"
    # Raises InvalidSignature if the signature doesn't verify — no exception is the assertion.
    public_key.verify(
        signature,
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )


def test_signature_differs_for_different_paths(key_pair):
    _path, key = key_pair
    sig_a = sign_request(key, "1700000000000", "GET", "/trade-api/v2/portfolio/balance")
    sig_b = sign_request(key, "1700000000000", "GET", "/trade-api/v2/portfolio/positions")
    assert sig_a != sig_b


def test_requests_carry_auth_headers(private_key_path):
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("KALSHI-ACCESS-KEY")
        seen["sig"] = request.headers.get("KALSHI-ACCESS-SIGNATURE")
        seen["ts"] = request.headers.get("KALSHI-ACCESS-TIMESTAMP")
        return httpx.Response(200, json={"balance": 12345})

    client = _client_with(private_key_path, handler)
    data = client.get_balance()
    assert data == {"balance": 12345}
    assert seen["key"] == "test-key-id"
    assert seen["sig"]
    assert seen["ts"] and seen["ts"].isdigit()


def test_fails_fast_on_401(private_key_path):
    def handler(request):
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(KalshiAuthError):
        _client_with(private_key_path, handler).get_balance()


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


def test_gives_up_after_max_retries(private_key_path, monkeypatch):
    def handler(request):
        return httpx.Response(500, text="boom")

    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(httpx.HTTPStatusError):
        _client_with(private_key_path, handler).get_fills()


def test_get_orders_passes_filters(private_key_path):
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"orders": []})

    client = _client_with(private_key_path, handler)
    client.get_orders(ticker="KXBTC15M-26SEP0512", status="resting")
    assert seen["params"]["ticker"] == "KXBTC15M-26SEP0512"
    assert seen["params"]["status"] == "resting"


# --- order placement (tasks.md 4.3) — mocked HTTP only, no live calls ------


def test_create_order_limit_sends_expected_body(private_key_path):
    seen = {}

    def handler(request):
        import json

        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"order": {"order_id": "o1", "status": "resting"}})

    client = _client_with(private_key_path, handler)
    client.create_order(
        market_ticker="KXBTC15M-26SEP0512",
        side="yes",
        action="buy",
        count=5,
        yes_price_cents=42,
    )
    assert seen["method"] == "POST"
    assert seen["path"] == "/portfolio/orders"
    assert seen["body"]["ticker"] == "KXBTC15M-26SEP0512"
    assert seen["body"]["side"] == "yes"
    assert seen["body"]["action"] == "buy"
    assert seen["body"]["count"] == 5
    assert seen["body"]["yes_price"] == 42
    assert seen["body"]["type"] == "limit"
    assert seen["body"]["client_order_id"]  # auto-generated


def test_create_order_uses_provided_client_order_id(private_key_path):
    seen = {}

    def handler(request):
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"order": {"order_id": "o1", "status": "resting"}})

    client = _client_with(private_key_path, handler)
    client.create_order(
        market_ticker="T",
        side="no",
        action="buy",
        count=1,
        no_price_cents=50,
        client_order_id="my-fixed-id",
    )
    assert seen["body"]["client_order_id"] == "my-fixed-id"


def test_create_order_limit_requires_a_price(private_key_path):
    client = _client_with(private_key_path, lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        client.create_order(market_ticker="T", side="yes", action="buy", count=1)


def test_create_order_market_type_omits_price(private_key_path):
    seen = {}

    def handler(request):
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"order": {"order_id": "o1", "status": "executed"}})

    client = _client_with(private_key_path, handler)
    client.create_order(market_ticker="T", side="yes", action="buy", count=1, order_type="market")
    assert seen["body"]["type"] == "market"
    assert "yes_price" not in seen["body"]
    assert "no_price" not in seen["body"]


def test_cancel_order_sends_delete(private_key_path):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(200, json={})

    client = _client_with(private_key_path, handler)
    client.cancel_order("order-123")
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/portfolio/orders/order-123"


def test_amend_order_sends_post_with_new_count(private_key_path):
    seen = {}

    def handler(request):
        import json

        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"order": {"order_id": "order-123"}})

    client = _client_with(private_key_path, handler)
    client.amend_order("order-123", count=3, yes_price_cents=44)
    assert seen["path"] == "/portfolio/orders/order-123/amend"
    assert seen["body"]["count"] == 3
    assert seen["body"]["yes_price"] == 44


def test_create_order_fails_fast_on_401(private_key_path):
    def handler(request):
        return httpx.Response(401, text="unauthorized")

    client = _client_with(private_key_path, handler)
    with pytest.raises(KalshiAuthError):
        client.create_order(
            market_ticker="T", side="yes", action="buy", count=1, yes_price_cents=50
        )


def test_create_order_refuses_prod_while_paper_trading(private_key_path):
    """spec: kalshi-authenticated-api 'Demo and production environments are
    structurally distinct' — prod + paper_trading=True is a misconfiguration,
    blocked before any network request."""
    client = KalshiAuthenticatedClient(
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
        client.create_order(
            market_ticker="T", side="yes", action="buy", count=1, yes_price_cents=50
        )
    client.close()


def test_amend_order_refuses_prod_while_paper_trading(private_key_path):
    client = KalshiAuthenticatedClient(
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
        client.amend_order("order-1", count=1)
    client.close()


def test_create_order_refuses_prod_when_paper_trading_false_without_phrase(private_key_path):
    """Disabling paper_trading alone is not enough — the live-trading
    confirmation phrase must also match exactly (tasks.md 4.7)."""
    client = KalshiAuthenticatedClient(
        key_id="k",
        private_key_path=private_key_path,
        use_demo_env=False,
        paper_trading=False,
    )
    client._client = httpx.Client(
        base_url="https://test",
        transport=httpx.MockTransport(lambda r: pytest.fail("no request should be made")),
    )
    with pytest.raises(KalshiConfigError):
        client.create_order(
            market_ticker="T", side="yes", action="buy", count=1, yes_price_cents=50
        )
    client.close()


def test_create_order_refuses_prod_with_wrong_phrase(private_key_path):
    client = KalshiAuthenticatedClient(
        key_id="k",
        private_key_path=private_key_path,
        use_demo_env=False,
        paper_trading=False,
        live_trading_confirmation_phrase="close enough",
    )
    client._client = httpx.Client(
        base_url="https://test",
        transport=httpx.MockTransport(lambda r: pytest.fail("no request should be made")),
    )
    with pytest.raises(KalshiConfigError):
        client.create_order(
            market_ticker="T", side="yes", action="buy", count=1, yes_price_cents=50
        )
    client.close()


def test_create_order_allowed_on_prod_when_paper_trading_false_and_phrase_matches(
    private_key_path,
):
    """The escape hatch: explicitly disabling paper_trading AND typing the
    exact confirmation phrase confirms intent to place a real order against
    production."""

    def handler(request):
        return httpx.Response(200, json={"order": {"order_id": "o1", "status": "resting"}})

    client = KalshiAuthenticatedClient(
        key_id="k",
        private_key_path=private_key_path,
        use_demo_env=False,
        paper_trading=False,
        live_trading_confirmation_phrase=LIVE_TRADING_CONFIRMATION_PHRASE,
        max_reads_per_second=1000,
    )
    client._client = httpx.Client(base_url="https://test", transport=httpx.MockTransport(handler))
    result = client.create_order(
        market_ticker="T", side="yes", action="buy", count=1, yes_price_cents=50
    )
    assert result["order"]["order_id"] == "o1"
    client.close()


def test_create_order_allowed_on_demo_regardless_of_paper_trading(private_key_path):
    def handler(request):
        return httpx.Response(200, json={"order": {"order_id": "o1", "status": "resting"}})

    client = KalshiAuthenticatedClient(
        key_id="k",
        private_key_path=private_key_path,
        use_demo_env=True,
        paper_trading=True,
        max_reads_per_second=1000,
    )
    client._client = httpx.Client(base_url="https://test", transport=httpx.MockTransport(handler))
    result = client.create_order(
        market_ticker="T", side="yes", action="buy", count=1, yes_price_cents=50
    )
    assert result["order"]["order_id"] == "o1"
    client.close()
