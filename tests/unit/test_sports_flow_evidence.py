from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from kalshi_bot.ai.sports_research import LocalOllamaEvidenceReviewer, require_strategy_candidate
from kalshi_bot.data.sports.evidence import (
    EvidenceCard,
    SourceAllowlist,
    eligible_cards,
    persist_evidence,
    validate_card,
)
from kalshi_bot.data.sports.flow import calculate_flow_features, copy_trading_status
from kalshi_bot.storage.models import Base, SportsEvidenceCard


def _card(**kwargs) -> EvidenceCard:
    values = {
        "provider": "official",
        "endpoint_url": "https://league.example/news",
        "claim": "lineup confirmed",
        "raw_content": "raw",
        "available_at": 90,
        "retrieved_at": 90,
        "publication_at": 80,
        "market_ticker": "M",
    }
    values.update(kwargs)
    return EvidenceCard(**values)


def test_flow_is_causal_deduplicated_and_identity_free():
    trades = [
        {
            "market_ticker": "M",
            "observed_at": 90,
            "available_at": 90,
            "price_cents": 50,
            "quantity": 2,
            "taker_side": "yes",
            "trade_id": "a",
        },
        {
            "market_ticker": "M",
            "observed_at": 90,
            "available_at": 90,
            "price_cents": 50,
            "quantity": 2,
            "taker_side": "yes",
            "trade_id": "a",
        },
        {
            "market_ticker": "M",
            "observed_at": 99,
            "available_at": 101,
            "price_cents": 50,
            "quantity": 9,
            "taker_side": "no",
            "trade_id": "future",
        },
    ]
    feature = calculate_flow_features(trades, [], market_ticker="M", decision_ts=100, window_s=20)
    assert feature.features["trade_count"] == 1
    assert feature.features["signed_trade_imbalance"] == 1.0
    assert feature.features["copy_trading"] == "copy_trading_unsupported"


def test_flow_empty_and_partial_books_are_safe():
    feature = calculate_flow_features(
        [],
        [
            {
                "market_ticker": "M",
                "observed_at": 100,
                "available_at": 100,
                "bids": [[48, 2]],
                "asks": [],
            }
        ],
        market_ticker="M",
        decision_ts=100,
    )
    assert feature.features["book_imbalance"] == 1.0
    assert feature.features["spread_cents"] is None


def test_copy_status_is_explicit():
    assert copy_trading_status()["status"] == "copy_trading_unsupported"


def test_evidence_allowlist_and_temporal_rejection():
    allow = SourceAllowlist(frozenset({"official"}), frozenset({"league.example"}))
    assert eligible_cards([_card()], decision_ts=100)
    assert not eligible_cards([_card(publication_at=120)], decision_ts=100)
    assert (
        validate_card(_card(endpoint_url="https://bad.example/x"), allow).status
        == "disallowed_source"
    )
    assert validate_card(_card(publication_at=None, observed_at=None), allow).status == "unusable"


def test_evidence_is_append_only_and_hashes_versions():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    allow = SourceAllowlist(frozenset({"official"}), frozenset({"league.example"}))
    with Session(engine) as session:
        persist_evidence(session, _card(), allowlist=allow)
        persist_evidence(
            session, _card(raw_content="changed", evidence_version="v2"), allowlist=allow
        )
        session.commit()
        rows = session.execute(select(SportsEvidenceCard)).scalars().all()
        assert len(rows) == 2 and rows[0].raw_content_hash != rows[1].raw_content_hash


class _FakeClient:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def post(self, *args, **kwargs):
        return httpx.Response(
            self.status, json=self.body, request=httpx.Request("POST", "http://test")
        )

    def close(self):
        pass


def test_local_review_success_and_malformed_fail_closed():
    good = {
        "message": {
            "content": json.dumps(
                {"summary": "confirmed", "classification": "supportive", "citations": []}
            )
        }
    }
    reviewer = LocalOllamaEvidenceReviewer(client=_FakeClient(good))
    assert reviewer.review(market_ticker="M", cards=[_card()], decision_ts=100).available
    reviewer = LocalOllamaEvidenceReviewer(client=_FakeClient({"message": {"content": "not-json"}}))
    assert not reviewer.review(market_ticker="M", cards=[_card()], decision_ts=100).available


def test_llm_boundary_requires_strategy_candidate():
    with pytest.raises(ValueError, match="strategy_candidate_required"):
        require_strategy_candidate(None)
    assert (
        require_strategy_candidate({"strategy_name": "flow", "market_ticker": "M"})["market_ticker"]
        == "M"
    )
