"""KalshiBRTISource — the CF Benchmarks passthrough BRTI reader.

No live network: an httpx MockTransport serves canned responses. Covers the
payload shapes the passthrough / CF Benchmarks docs describe, transient
errors (returned as a skipped tick), and auth failure (raises).
"""

from __future__ import annotations

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from kalshi_bot.data.brti.kalshi_source import KalshiBRTISource, _parse_values_payload


@pytest.fixture
def fake_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _source(handler, key: rsa.RSAPrivateKey) -> KalshiBRTISource:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://external-api.kalshi.com/trade-api/v2")
    return KalshiBRTISource(
        key_id="test-key", private_key_path="unused", _private_key=key, _client=client
    )


def test_parses_nested_payload_shape():
    inner = {"type": "value", "id": "BRTI", "time": 1_788_700_000_123, "value": "111203.44"}
    body = {"data": {"serverTime": "2026-09-07T00:00:00.500Z", "payload": inner}}
    reading = _parse_values_payload(body, source="kalshi:cfbenchmarks/BRTI")
    assert reading is not None
    assert reading.observed_at == 1_788_700_000  # ms -> s
    assert reading.value == pytest.approx(111203.44)
    assert reading.available_at is None  # poll_brti stamps receipt time
    assert reading.extra["observed_at_ms"] == 1_788_700_000_123


def test_parses_flat_payload_shape():
    inner = {"type": "value", "id": "BRTI", "time": 1_788_700_060_000, "value": "111250.10"}
    reading = _parse_values_payload({"data": inner}, source="s")
    assert reading is not None
    assert reading.observed_at == 1_788_700_060


def test_parses_values_list_shape():
    body = {"payload": {"values": [{"id": "BRTI", "time": 1_788_700_120_000, "value": "111300"}]}}
    reading = _parse_values_payload(body, source="s")
    assert reading is not None
    assert reading.value == pytest.approx(111300.0)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"data": {}},
        {"data": {"payload": {"id": "BRTI"}}},  # no value/time
        {"data": {"payload": {"value": "0", "time": 1}}},  # non-positive
        {"data": {"payload": {"value": "abc", "time": 1_788_700_000_000}}},  # unparseable
        "not a dict",
    ],
)
def test_unusable_payloads_return_none(body):
    assert _parse_values_payload(body, source="s") is None


def test_fetch_returns_reading_on_200(fake_key):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/trade-api/v2/cfbenchmarks/values"
        assert request.url.params["id"] == "BRTI"
        assert "KALSHI-ACCESS-SIGNATURE" in request.headers
        assert "KALSHI-ACCESS-TIMESTAMP" in request.headers
        inner = {"id": "BRTI", "time": 1_788_700_000_000, "value": "111000.00"}
        return httpx.Response(200, json={"data": {"payload": inner}})

    with _source(handler, fake_key) as src:
        reading = src.fetch()
    assert reading is not None
    assert reading.value == pytest.approx(111000.0)


def test_fetch_returns_none_on_500(fake_key):
    with _source(lambda r: httpx.Response(503, text="upstream unavailable"), fake_key) as src:
        assert src.fetch() is None


def test_fetch_returns_none_on_transport_error(fake_key):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    with _source(handler, fake_key) as src:
        assert src.fetch() is None


def test_fetch_raises_on_auth_failure(fake_key):
    src = _source(lambda r: httpx.Response(403, text="forbidden"), fake_key)
    with src, pytest.raises(RuntimeError, match="auth failed"):
        src.fetch()


def test_fetch_returns_none_on_non_json(fake_key):
    with _source(lambda r: httpx.Response(200, text="<html>nope</html>"), fake_key) as src:
        assert src.fetch() is None
