"""Local pre-trade veto gate (tasks.md 7.1): fail-closed on every failure
mode. All HTTP mocked — no call to a real Ollama instance here."""

from __future__ import annotations

import json

import httpx
import pytest

from kalshi_bot.ai.local_review import (
    LocalReviewClient,
    TradeCandidate,
    VetoVerdict,
    to_veto_verdict_record,
)


def _candidate(**overrides) -> TradeCandidate:
    defaults = dict(
        market_ticker="KXBTC15M-TEST",
        strategy_name="trend_scalp",
        action="BUY_YES",
        entry_price_cents=52,
        fee_adjusted_edge=0.08,
        confidence=0.6,
        minutes_to_expiry=12.0,
        trend_zscore=1.2,
    )
    defaults.update(overrides)
    return TradeCandidate(**defaults)


def _client_with(handler) -> LocalReviewClient:
    client = LocalReviewClient()
    client._client = httpx.Client(base_url="https://test", transport=httpx.MockTransport(handler))
    return client


def _ollama_response(message_content: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"content": message_content}})


def test_well_formed_approval_is_approved():
    def handler(request):
        return _ollama_response(json.dumps({"approved": True, "confidence": 0.8, "reason": "ok"}))

    client = _client_with(handler)
    verdict = client.review(_candidate())
    assert verdict.approved is True
    assert verdict.reason == "ok"
    assert verdict.confidence == pytest.approx(0.8)


def test_well_formed_rejection_is_rejected():
    def handler(request):
        return _ollama_response(
            json.dumps({"approved": False, "confidence": 0.3, "reason": "too risky"})
        )

    client = _client_with(handler)
    verdict = client.review(_candidate())
    assert verdict.approved is False
    assert verdict.reason == "too risky"


def test_request_sends_expected_shape():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return _ollama_response(json.dumps({"approved": True, "reason": "ok"}))

    client = _client_with(handler)
    client.review(_candidate())
    assert seen["body"]["format"] == "json"
    assert seen["body"]["stream"] is False
    assert seen["body"]["messages"][1]["content"]
    payload = json.loads(seen["body"]["messages"][1]["content"])
    assert payload["market_ticker"] == "KXBTC15M-TEST"
    assert payload["action"] == "BUY_YES"


def test_http_error_fails_closed():
    def handler(request):
        return httpx.Response(500, text="ollama down")

    client = _client_with(handler)
    verdict = client.review(_candidate())
    assert verdict.approved is False
    assert verdict.reason.startswith("request_failed")


def test_connection_error_fails_closed():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    client = _client_with(handler)
    verdict = client.review(_candidate())
    assert verdict.approved is False
    assert verdict.reason.startswith("request_failed")


def test_empty_content_fails_closed():
    def handler(request):
        return httpx.Response(200, json={"message": {"content": ""}})

    client = _client_with(handler)
    verdict = client.review(_candidate())
    assert verdict.approved is False
    assert verdict.reason == "empty_response"


def test_malformed_json_fails_closed():
    def handler(request):
        return _ollama_response("not json at all {{{")

    client = _client_with(handler)
    verdict = client.review(_candidate())
    assert verdict.approved is False
    assert verdict.reason == "malformed_json"
    assert verdict.raw_response == "not json at all {{{"


def test_unexpected_shape_fails_closed():
    def handler(request):
        return _ollama_response(json.dumps({"verdict": "yes"}))  # no "approved" key

    client = _client_with(handler)
    verdict = client.review(_candidate())
    assert verdict.approved is False
    assert verdict.reason == "unexpected_shape"


def test_non_boolean_approved_fails_closed():
    def handler(request):
        return _ollama_response(json.dumps({"approved": "yes", "reason": "sure"}))

    client = _client_with(handler)
    verdict = client.review(_candidate())
    assert verdict.approved is False
    assert verdict.reason == "non_boolean_approved"


def test_missing_reason_defaults_gracefully():
    def handler(request):
        return _ollama_response(json.dumps({"approved": True}))

    client = _client_with(handler)
    verdict = client.review(_candidate())
    assert verdict.approved is True
    assert verdict.reason == "no_reason_given"


def test_non_numeric_confidence_becomes_none():
    def handler(request):
        return _ollama_response(
            json.dumps({"approved": True, "confidence": "high", "reason": "ok"})
        )

    client = _client_with(handler)
    verdict = client.review(_candidate())
    assert verdict.approved is True
    assert verdict.confidence is None


def test_raw_response_preserved_even_on_failure():
    def handler(request):
        return _ollama_response(json.dumps({"approved": False, "reason": "no"}))

    client = _client_with(handler)
    verdict = client.review(_candidate())
    assert verdict.raw_response is not None
    assert "approved" in verdict.raw_response


def test_verdict_is_frozen_dataclass():
    verdict = VetoVerdict(approved=True, reason="ok")
    with pytest.raises(AttributeError):
        verdict.approved = False  # type: ignore[misc]


def test_latency_is_recorded_on_success():
    def handler(request):
        return _ollama_response(json.dumps({"approved": True, "reason": "ok"}))

    client = _client_with(handler)
    verdict = client.review(_candidate())
    assert verdict.latency_ms is not None
    assert verdict.latency_ms >= 0


def test_latency_is_recorded_on_failure():
    def handler(request):
        return httpx.Response(500, text="down")

    client = _client_with(handler)
    verdict = client.review(_candidate())
    assert verdict.latency_ms is not None


def test_to_veto_verdict_record_maps_fields():
    verdict = VetoVerdict(
        approved=True,
        reason="ok",
        confidence=0.7,
        raw_response='{"approved": true}',
        latency_ms=500,
    )
    record = to_veto_verdict_record(verdict, model="qwen3:14b", signal_id=42)
    assert record.signal_id == 42
    assert record.model == "qwen3:14b"
    assert record.approved is True
    assert record.confidence == pytest.approx(0.7)
    assert record.reason == "ok"
    assert record.raw_response == '{"approved": true}'
    assert record.latency_ms == 500


def test_to_veto_verdict_record_allows_no_signal_id():
    verdict = VetoVerdict(approved=False, reason="no")
    record = to_veto_verdict_record(verdict, model="qwen3:14b")
    assert record.signal_id is None
