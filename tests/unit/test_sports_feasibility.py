from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from kalshi_bot.data.sports.capture import capture_report, record_gaps
from kalshi_bot.data.sports.classifier import RejectionReason, classify_market
from kalshi_bot.data.sports.discovery import DiscoveryConfig, SportsDiscovery
from kalshi_bot.data.sports.external import ExternalSportsObservation
from kalshi_bot.data.sports.validation import (
    SportsObservation,
    chronological_evaluation,
    feasibility_report,
    simulate_fill,
    time_to_event_bucket,
)
from kalshi_bot.storage.models import Base, SportsCandle, SportsCaptureGap


def _market(title="Team A vs Team B", **extra):
    return {
        "ticker": "KXGAME-1-A",
        "event_ticker": "KXGAME-1",
        "sport": "NFL",
        "title": title,
        "rules_primary": "official league result",
        **extra,
    }


def test_classifier_accepts_binary_game_and_rejects_shapes():
    assert classify_market(_market()).eligible
    assert classify_market(_market("Season champion")).reason == RejectionReason.FUTURES
    assert classify_market(_market("Player points prop")).reason == RejectionReason.PLAYER_PROP
    assert classify_market(_market("Same game parlay")).reason == RejectionReason.COMBO
    assert (
        classify_market(_market(outcomes=["A", "B", "C"])).reason == RejectionReason.MULTI_OUTCOME
    )
    assert (
        classify_market({"ticker": "M", "event_ticker": "E", "sport": "NFL"}).reason
        == RejectionReason.UNKNOWN_RULES
    )


def test_external_observation_requires_causal_provenance():
    row = ExternalSportsObservation(
        "provider", "/odds", 100, 105, {"p": 0.5}, {"source": "fixture"}
    )
    assert row.available_at >= row.observed_at
    with pytest.raises(ValueError):
        ExternalSportsObservation("provider", "/odds", 100, 99, None, {})


def test_discovery_persists_eligible_and_one_sided_rejection():
    class Client:
        def get_series(self, ticker):
            return {"ticker": ticker, "sport": "NFL", "title": "NFL"}

        def iter_markets(self, **kwargs):
            yield _market(
                yes_bid=45,
                yes_ask=47,
                yes_bid_size=10,
                yes_ask_size=8,
                open_interest=20,
                volume=100,
            )
            yield _market(
                "high volume but one-sided",
                ticker="KXGAME-1-B",
                yes_bid=None,
                yes_ask=47,
                yes_bid_size=0,
                yes_ask_size=8,
                open_interest=20,
                volume=100,
            )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        rows = SportsDiscovery(Client(), config=DiscoveryConfig()).discover(
            session, series_tickers=["NFL"]
        )
        assert [row.classification.eligible for row in rows] == [True, False]
        assert rows[1].classification.reason == RejectionReason.NOT_LIQUID


def test_gap_report_has_no_synthetic_rows():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                SportsCandle(
                    series_ticker="S",
                    market_ticker="M",
                    period_minutes=1,
                    end_period_ts=60,
                    observed_at=0,
                    available_at=1,
                ),
                SportsCandle(
                    series_ticker="S",
                    market_ticker="M",
                    period_minutes=1,
                    end_period_ts=240,
                    observed_at=180,
                    available_at=181,
                ),
            ]
        )
        session.commit()
        assert record_gaps(session, expected_interval_s=60, threshold=1.5) == 1
        assert len(session.execute(select(SportsCandle)).scalars().all()) == 2
        assert capture_report(session)["gap_count"] == 1
        assert session.execute(select(SportsCaptureGap)).scalar_one().start_ts == 0


def _obs(
    i: int, *, candidate: float = 0.7, market: float = 0.5, outcome: int = 1, depth: float = 10
) -> SportsObservation:
    return SportsObservation(
        "M", 1_000 + i * 60, 1_000 + i * 60, 10_000, market, candidate, outcome, 52, 48, depth, 0.02
    )


def test_fill_rejects_friction_and_handles_partial_depth():
    row = _obs(0, candidate=0.51, market=0.5, depth=0.5)
    result = simulate_fill(row, edge_threshold=0.0, slippage_cents=2)
    assert result.eligible and result.quantity == 0.5
    assert result.fee_usd > 0
    assert (
        simulate_fill(_obs(0, candidate=0.5), edge_threshold=0.0).rejection_reason
        == "edge_below_threshold"
    )


def test_tte_buckets_and_holdout_leakage_guard():
    assert time_to_event_bucket(3) == "0-5m"
    assert time_to_event_bucket(90) == "30-120m"
    rows = [_obs(i) for i in range(40)]
    result = chronological_evaluation(rows, holdout_ts=1_000 + 30 * 60, min_train_samples=10)
    assert result["valid"] is True
    assert result["train_count"] == 30


def test_feasibility_small_sample_is_insufficient_and_execution_disabled():
    report = feasibility_report([_obs(i) for i in range(4)], holdout_ts=1_000, min_sample_size=10)
    assert report.outcome == "insufficient_data"
    assert report.execution_enabled is False
