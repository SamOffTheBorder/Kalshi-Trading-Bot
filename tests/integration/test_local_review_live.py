"""Live check against a real local Ollama instance (tasks.md 7.1).

Run explicitly: pytest -m integration
Requires Ollama running on localhost:11434 with a qwen3-14b-class model
pulled. Skips (not fails) if Ollama is unreachable — this test proves the
client's wire format actually round-trips against a real model, it does not
gate CI on a local service being up.
"""

from __future__ import annotations

import httpx
import pytest

from kalshi_bot.ai.local_review import LocalReviewClient, TradeCandidate

pytestmark = pytest.mark.integration

LOCAL_MODEL = "huihui_ai/qwen3-abliterated:14b-q4_K_M"


def _ollama_reachable() -> bool:
    try:
        httpx.get("http://localhost:11434/api/version", timeout=2.0).raise_for_status()
        return True
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not _ollama_reachable(), reason="Ollama not reachable on localhost:11434")
def test_veto_client_round_trips_against_real_local_model():
    candidate = TradeCandidate(
        market_ticker="KXBTC15M-26SEP0512",
        strategy_name="trend_scalp",
        action="BUY_YES",
        entry_price_cents=52,
        fee_adjusted_edge=0.08,
        confidence=0.6,
        minutes_to_expiry=12.0,
        trend_zscore=1.2,
    )
    with LocalReviewClient(model=LOCAL_MODEL, timeout_s=60.0) as client:
        verdict = client.review(candidate)

    # We don't assert a specific verdict — the model's actual judgment isn't
    # what's under test. What matters: the client got a real HTTP 200 back
    # from a real model and successfully parsed a well-formed verdict out of
    # it, i.e. the round trip (request shape -> Ollama -> response shape)
    # actually works, not just against a mock.
    assert isinstance(verdict.approved, bool)
    assert verdict.reason not in ("request_failed", "empty_response", "malformed_json")
    assert verdict.raw_response is not None
