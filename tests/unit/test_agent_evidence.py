from __future__ import annotations

from kalshi_bot.agents.contracts import TradeCandidateEnvelope
from kalshi_bot.agents.evidence import (
    build_evidence_bundle,
    perp_candidate_from_mapping,
    prediction_candidate_from_mapping,
    project_for_role,
    project_perp_evidence,
    project_prediction_evidence,
    project_sports_evidence,
    sports_candidate_from_mapping,
)


def _candidate(**changes):
    values = dict(
        candidate_id="candidate-1",
        domain="prediction",
        specialization_key="prediction/BTC/15m",
        instrument_id="KXBTC15M",
        strategy_name="test",
        strategy_version="1",
        decision_ts=100,
        proposed_action="BUY_YES",
        evidence_manifest_hash="manifest",
    )
    values.update(changes)
    return TradeCandidateEnvelope(**values)


def test_bundle_excludes_late_and_invalid_rows_and_is_stable():
    bundle = build_evidence_bundle(
        _candidate(),
        [
            {
                "source": "fixture",
                "kind": "quote",
                "claim": "fresh quote",
                "observed_at": 99,
                "available_at": 99,
                "payload": {"yes_ask": 52},
            },
            {
                "source": "future",
                "kind": "quote",
                "claim": "too late",
                "observed_at": 101,
                "available_at": 101,
            },
            {"source": "bad", "kind": "quote"},
        ],
        bundle_id="bundle-1",
    )
    assert len(bundle.items) == 1
    assert len(bundle.excluded_items) == 2
    assert bundle.bundle_hash == bundle.computed_hash()


def test_domain_projections_and_role_projection_are_scoped_and_redacted():
    candidate = _candidate(domain="sports", specialization_key="sports/nba/nba/moneyline")
    bundle = build_evidence_bundle(
        candidate,
        [
            {
                "source": "market",
                "kind": "market",
                "claim": "rules",
                "observed_at": 99,
                "available_at": 99,
                "payload": {"rule": "official", "private_key": "secret"},
            },
            {
                "source": "book",
                "kind": "quote",
                "claim": "liquidity",
                "observed_at": 99,
                "available_at": 99,
                "payload": {"order_id": "live-order", "bid": 48},
            },
            {
                "source": "crypto",
                "kind": "spot",
                "claim": "unrelated",
                "observed_at": 99,
                "available_at": 99,
            },
        ],
        bundle_id="bundle-sports",
    )
    assert len(project_prediction_evidence(bundle)) == 0
    assert len(project_perp_evidence(bundle)) == 0
    assert len(project_sports_evidence(bundle)) == 2
    projection = project_for_role(candidate, bundle, "execution_liquidity")
    assert len(projection["items"]) == 1
    assert "private_key" not in str(projection)
    assert "order_id" not in str(projection)


def test_domain_candidate_adapters_normalize_strategy_outputs():
    raw = {
        "candidate_id": "candidate-2",
        "instrument_id": "KXBTC15M",
        "strategy_name": "strategy",
        "strategy_version": "1",
        "decision_ts": 100,
        "proposed_price": 51,
        "proposed_size": 2,
        "evidence_manifest_hash": "manifest",
    }
    assert prediction_candidate_from_mapping(
        raw, specialization_key="prediction/BTC/15m", action="BUY_YES"
    ).domain == "prediction"
    assert perp_candidate_from_mapping(
        {**raw, "instrument_id": "KALSHI-BTC-PERP"},
        specialization_key="perp/BTC/directional",
        action="LONG",
    ).proposed_action == "LONG"
    assert sports_candidate_from_mapping(
        {**raw, "instrument_id": "NBA-MARKET"},
        specialization_key="sports/nba/nba/moneyline",
        action="BUY_NO",
    ).domain == "sports"
