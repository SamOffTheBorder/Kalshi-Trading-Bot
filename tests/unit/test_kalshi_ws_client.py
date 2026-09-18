"""Kalshi authenticated WebSocket client: auth headers, subscribe shape,
sequence-gap detection/resync.

All tests run an in-process fake WebSocket server on localhost via
`websockets.serve` — no connection is ever made to Kalshi's demo or
production WebSocket endpoints.
"""

from __future__ import annotations

import json

import pytest
import websockets
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from kalshi_bot.execution.kalshi_ws_client import KalshiWebSocketClient


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


async def _run_against_fake_server(client, channels, handler, **kwargs):
    """Start a local fake server, point the client at it via the `connect`
    override, collect messages until the handler's send queue is exhausted."""
    seen_headers: dict[str, str] = {}
    received_subscribe: dict = {}

    async def server_handler(ws):
        # websockets.Headers is case-insensitive but iterates lowercased
        # keys; snapshot via its own .get so lookups by canonical case work.
        for name in ("KALSHI-ACCESS-KEY", "KALSHI-ACCESS-SIGNATURE", "KALSHI-ACCESS-TIMESTAMP"):
            value = ws.request.headers.get(name)
            if value is not None:
                seen_headers[name] = value
        raw = await ws.recv()
        received_subscribe.update(json.loads(raw))
        await handler(ws)

    async with websockets.serve(server_handler, "localhost", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://localhost:{port}"

        def connect_override(_url, **kw):
            return websockets.connect(url, **kw)

        results = []
        agen = client.messages(channels, connect=connect_override, **kwargs)
        try:
            async for message in agen:
                results.append(message)
        except websockets.exceptions.ConnectionClosedOK:
            pass
    return results, seen_headers, received_subscribe


@pytest.mark.asyncio
async def test_subscribe_command_shape(private_key_path):
    client = KalshiWebSocketClient(
        key_id="test-key-id", private_key_path=private_key_path, use_demo_env=True
    )

    async def handler(ws):
        await ws.close()

    _results, _headers, subscribed = await _run_against_fake_server(
        client, ["ticker"], handler, market_ticker="KXBTC15M-26SEP0512"
    )
    assert subscribed["cmd"] == "subscribe"
    assert subscribed["id"] == 1
    assert subscribed["params"]["channels"] == ["ticker"]
    assert subscribed["params"]["market_ticker"] == "KXBTC15M-26SEP0512"


@pytest.mark.asyncio
async def test_connection_carries_auth_headers(private_key_path):
    client = KalshiWebSocketClient(
        key_id="test-key-id", private_key_path=private_key_path, use_demo_env=True
    )

    async def handler(ws):
        await ws.close()

    _results, headers, _subscribed = await _run_against_fake_server(client, ["ticker"], handler)
    assert headers.get("KALSHI-ACCESS-KEY") == "test-key-id"
    assert headers.get("KALSHI-ACCESS-SIGNATURE")
    assert headers.get("KALSHI-ACCESS-TIMESTAMP", "").isdigit()


@pytest.mark.asyncio
async def test_cmd_id_increments_across_calls(private_key_path):
    client = KalshiWebSocketClient(
        key_id="test-key-id", private_key_path=private_key_path, use_demo_env=True
    )
    first = client._subscribe_command(["ticker"])
    second = client._subscribe_command(["fill"])
    assert first["id"] == 1
    assert second["id"] == 2


@pytest.mark.asyncio
async def test_messages_are_yielded_in_order(private_key_path):
    client = KalshiWebSocketClient(
        key_id="test-key-id", private_key_path=private_key_path, use_demo_env=True
    )

    async def handler(ws):
        await ws.send(json.dumps({"type": "ticker", "sid": 1, "msg": {"price_dollars": "0.50"}}))
        await ws.send(json.dumps({"type": "ticker", "sid": 1, "msg": {"price_dollars": "0.51"}}))
        await ws.close()

    results, _headers, _subscribed = await _run_against_fake_server(client, ["ticker"], handler)
    assert [m["msg"]["price_dollars"] for m in results] == ["0.50", "0.51"]


@pytest.mark.asyncio
async def test_no_gap_when_seq_increments_by_one(private_key_path):
    client = KalshiWebSocketClient(
        key_id="test-key-id", private_key_path=private_key_path, use_demo_env=True
    )

    async def handler(ws):
        await ws.send(json.dumps({"type": "orderbook_snapshot", "sid": 2, "seq": 1, "msg": {}}))
        await ws.send(json.dumps({"type": "orderbook_delta", "sid": 2, "seq": 2, "msg": {}}))
        await ws.close()

    results, _headers, _subscribed = await _run_against_fake_server(
        client, ["orderbook_delta"], handler
    )
    assert not any(m.get("type") == "resync_required" for m in results)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_sequence_gap_yields_resync_required(private_key_path):
    client = KalshiWebSocketClient(
        key_id="test-key-id", private_key_path=private_key_path, use_demo_env=True
    )

    async def handler(ws):
        await ws.send(json.dumps({"type": "orderbook_snapshot", "sid": 2, "seq": 1, "msg": {}}))
        await ws.send(json.dumps({"type": "orderbook_delta", "sid": 2, "seq": 5, "msg": {}}))
        await ws.close()

    results, _headers, _subscribed = await _run_against_fake_server(
        client, ["orderbook_delta"], handler
    )
    resync_messages = [m for m in results if m.get("type") == "resync_required"]
    assert len(resync_messages) == 1
    assert resync_messages[0]["sid"] == 2
    assert resync_messages[0]["expected_seq"] == 2
    assert resync_messages[0]["got_seq"] == 5
    # The out-of-order message itself is still yielded after the marker.
    assert results[-1]["seq"] == 5


@pytest.mark.asyncio
async def test_messages_without_seq_pass_through_untouched(private_key_path):
    client = KalshiWebSocketClient(
        key_id="test-key-id", private_key_path=private_key_path, use_demo_env=True
    )

    async def handler(ws):
        await ws.send(json.dumps({"type": "fill", "sid": 3, "msg": {"trade_id": "t1"}}))
        await ws.close()

    results, _headers, _subscribed = await _run_against_fake_server(client, ["fill"], handler)
    assert results == [{"type": "fill", "sid": 3, "msg": {"trade_id": "t1"}}]
