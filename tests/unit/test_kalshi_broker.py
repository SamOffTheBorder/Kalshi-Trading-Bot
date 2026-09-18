"""KalshiBroker: BrokerAdapter implementation wrapping KalshiAuthenticatedClient.

All HTTP is mocked — no live call is made against demo or production here.
"""

from __future__ import annotations

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from kalshi_bot.execution.broker_protocol import OrderRequest
from kalshi_bot.execution.kalshi_broker import KalshiBroker
from kalshi_bot.execution.kalshi_client import KalshiAuthenticatedClient


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


def _broker_with(private_key_path, handler) -> KalshiBroker:
    client = KalshiAuthenticatedClient(
        key_id="test-key-id",
        private_key_path=private_key_path,
        use_demo_env=True,
        max_reads_per_second=1000,
    )
    client._client = httpx.Client(base_url="https://test", transport=httpx.MockTransport(handler))
    return KalshiBroker(client)


@pytest.mark.asyncio
async def test_get_account_balance_converts_cents_to_dollars(private_key_path):
    def handler(request):
        return httpx.Response(200, json={"balance": 5773})

    broker = _broker_with(private_key_path, handler)
    assert await broker.get_account_balance() == pytest.approx(57.73)


@pytest.mark.asyncio
async def test_get_open_positions_maps_side_from_sign(private_key_path):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "market_positions": [
                    {"ticker": "A", "position": 5, "market_exposure_dollars": 0.45},
                    {"ticker": "B", "position": -3, "market_exposure_dollars": 0.30},
                    {"ticker": "C", "position": 0, "market_exposure_dollars": 0.0},
                ]
            },
        )

    broker = _broker_with(private_key_path, handler)
    positions = await broker.get_open_positions()
    assert len(positions) == 2  # zero-quantity position dropped
    assert positions[0].market_ticker == "A"
    assert positions[0].side == "yes"
    assert positions[0].quantity == 5
    assert positions[1].side == "no"
    assert positions[1].quantity == 3


@pytest.mark.asyncio
async def test_place_order_executed_reports_filled(private_key_path):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "order": {
                    "order_id": "o1",
                    "status": "executed",
                    "taker_fill_count": 5,
                    "yes_price": 42,
                }
            },
        )

    broker = _broker_with(private_key_path, handler)
    result = await broker.place_order(
        OrderRequest(market_ticker="T", side="yes", quantity=5, limit_price_cents=42)
    )
    assert result.status == "filled"
    assert result.quantity == 5
    assert result.fill_price_cents == 42


@pytest.mark.asyncio
async def test_place_order_resting_unfilled_reports_rejected(private_key_path):
    def handler(request):
        return httpx.Response(
            200,
            json={"order": {"order_id": "o1", "status": "resting", "taker_fill_count": 0}},
        )

    broker = _broker_with(private_key_path, handler)
    result = await broker.place_order(
        OrderRequest(market_ticker="T", side="yes", quantity=5, limit_price_cents=42)
    )
    assert result.status == "rejected"
    assert result.reject_reason == "resting_unfilled"


@pytest.mark.asyncio
async def test_place_order_market_type_when_no_limit_price(private_key_path):
    seen = {}

    def handler(request):
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"order": {"order_id": "o1", "status": "executed", "taker_fill_count": 1}}
        )

    broker = _broker_with(private_key_path, handler)
    await broker.place_order(OrderRequest(market_ticker="T", side="yes", quantity=1))
    assert seen["body"]["type"] == "market"


@pytest.mark.asyncio
async def test_cancel_order_calls_delete(private_key_path):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        return httpx.Response(200, json={})

    broker = _broker_with(private_key_path, handler)
    await broker.cancel_order("order-123")
    assert seen["method"] == "DELETE"


@pytest.mark.asyncio
async def test_get_market_snapshot_not_implemented(private_key_path):
    broker = _broker_with(private_key_path, lambda r: httpx.Response(200, json={}))
    with pytest.raises(NotImplementedError):
        await broker.get_market_snapshot("T")
