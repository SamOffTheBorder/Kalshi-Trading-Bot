from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from kalshi_bot.domain.prediction import (
    AssessmentStatus,
    ContractSide,
    EventIdentity,
    FeeAggregationScope,
    FeeEstimate,
    FeeFill,
    FeeSchedule,
    InstrumentIdentity,
    MarketQuote,
    PredictionEvent,
    PredictionMarket,
    RawMarketRecord,
    RawReference,
    RecordAssessment,
    ResolutionRule,
    ScanCandidate,
    Venue,
)


def _raw() -> RawReference:
    return RawReference(source="fixture", content_hash="abc")


def _event(venue: Venue = Venue.KALSHI) -> PredictionEvent:
    return PredictionEvent(
        identity=EventIdentity(
            venue=venue,
            external_id="same-id",
            canonical_id=f"{venue}:event:1",
            real_world_event_id="event-group-1",
            aliases=("Home Team",),
        ),
        sport="baseball",
        league="MLB",
        participants=("Home Team", "Away Team"),
        starts_at=datetime(2026, 9, 23, tzinfo=UTC),
        status="open",
        raw=_raw(),
    )


def _instrument(venue: Venue = Venue.KALSHI) -> InstrumentIdentity:
    return InstrumentIdentity(
        venue=venue,
        external_id="same-market",
        canonical_id=f"{venue}:market:1:yes",
        event_id=f"{venue}:event:1",
        side=ContractSide.YES,
    )


def _qualified() -> RecordAssessment:
    return RecordAssessment(status=AssessmentStatus.QUALIFIED)


def _market() -> PredictionMarket:
    event = _event()
    return PredictionMarket(
        identity=_instrument(),
        event=event,
        title="Home team wins",
        status="open",
        closes_at=event.starts_at,
        resolution_rule=ResolutionRule(
            text="Wins including overtime",
            source="fixture",
            content_hash="rule",
            outcome_orientation="home_team",
        ),
        assessment=_qualified(),
        raw=_raw(),
    )


def _quote() -> MarketQuote:
    now = datetime(2026, 9, 23, tzinfo=UTC)
    return MarketQuote(
        instrument=_instrument(),
        bid=Decimal("0.70"),
        ask=Decimal("0.71"),
        bid_quantity=Decimal("10"),
        ask_quantity=Decimal("10"),
        payout=Decimal("1"),
        tick_size=Decimal("0.01"),
        quantity_step=Decimal("1"),
        minimum_quantity=Decimal("1"),
        source_at=now,
        observed_at=now,
        available_at=now,
        retrieved_at=now,
        raw=_raw(),
    )


def _fees() -> FeeEstimate:
    now = datetime(2026, 9, 23, tzinfo=UTC)
    fill = FeeFill(
        fill_id="level-1",
        price=Decimal("0.71"),
        quantity=Decimal("2"),
        notional=Decimal("1.42"),
        fee=Decimal("0.03"),
    )
    return FeeEstimate(
        instrument=_instrument(),
        schedule=FeeSchedule(
            venue=Venue.KALSHI,
            coefficient=Decimal("0.07"),
            effective_date=date(2026, 1, 1),
            source="fixture",
            formula_version="fixture-v1",
            rounding_version="ceiling-cent-v1",
            aggregation_scope=FeeAggregationScope.FILL,
            verified_at=now,
        ),
        fills=(fill,),
        total_quantity=Decimal("2"),
        total_notional=Decimal("1.42"),
        total_fee=Decimal("0.03"),
        calculated_at=now,
    )


def test_venue_namespaces_identical_external_ids():
    kalshi = _event(Venue.KALSHI)
    polymarket = _event(Venue.POLYMARKET_US)

    assert kalshi.identity.external_id == polymarket.identity.external_id
    assert kalshi.identity.canonical_id != polymarket.identity.canonical_id
    assert kalshi.identity.venue != polymarket.identity.venue


def test_quote_preserves_decimal_precision_and_causal_provenance():
    now = datetime(2026, 9, 23, tzinfo=UTC)
    quote = MarketQuote(
        instrument=_instrument(),
        bid=Decimal("0.70125"),
        ask=Decimal("0.70375"),
        bid_quantity=Decimal("3.5"),
        ask_quantity=Decimal("2.25"),
        payout=Decimal("1"),
        tick_size=Decimal("0.00001"),
        quantity_step=Decimal("0.25"),
        minimum_quantity=Decimal("1"),
        source_at=now,
        observed_at=now,
        available_at=now,
        retrieved_at=now,
        raw=_raw(),
    )
    assert quote.ask == Decimal("0.70375")
    with pytest.raises(ValidationError, match="Decimal"):
        MarketQuote.model_validate({**quote.model_dump(), "ask": 0.7})


def test_incomplete_rule_is_not_rankable():
    event = _event()
    market = PredictionMarket(
        identity=_instrument(),
        event=event,
        title="Home team wins",
        status="open",
        closes_at=event.starts_at,
        resolution_rule=ResolutionRule(
            text="Wins", source="fixture", content_hash="rule", outcome_orientation=None
        ),
        assessment=RecordAssessment(
            status=AssessmentStatus.MISSING_FIELDS,
            missing_fields=("resolution_rule.outcome_orientation",),
        ),
        raw=_raw(),
    )
    assert market.rankable is False


def test_incomplete_raw_market_is_preserved_with_explicit_missing_fields():
    record = RawMarketRecord(
        venue=Venue.POLYMARKET_US,
        event_external_id="event-1",
        market_external_id="market-1",
        side=None,
        resolution_rule=None,
        assessment=RecordAssessment(
            status=AssessmentStatus.MISSING_FIELDS,
            missing_fields=("side", "resolution_rule"),
        ),
        raw=_raw(),
    )

    assert record.raw.content_hash == "abc"
    assert record.assessment.status is AssessmentStatus.MISSING_FIELDS

    with pytest.raises(ValidationError, match="cannot qualify"):
        PredictionMarket(
            identity=_instrument(),
            event=_event(),
            title="Incomplete market",
            status="open",
            closes_at=datetime(2026, 9, 23, tzinfo=UTC),
            resolution_rule=None,
            assessment=_qualified(),
            raw=_raw(),
        )


def test_unsupported_assessment_requires_structured_evidence():
    with pytest.raises(ValidationError, match="identify unsupported data"):
        RecordAssessment(status=AssessmentStatus.UNSUPPORTED)

    assessment = RecordAssessment(
        status=AssessmentStatus.UNSUPPORTED,
        unsupported_fields=("market_type:three_way",),
    )
    assert assessment.unsupported_fields == ("market_type:three_way",)


def test_fee_estimate_preserves_structured_fill_totals_and_decimal_inputs():
    estimate = _fees()
    assert estimate.total_fee == Decimal("0.03")
    assert estimate.fills[0].notional == Decimal("1.42")

    with pytest.raises(ValidationError, match="total fee"):
        FeeEstimate.model_validate({**estimate.model_dump(), "total_fee": Decimal("0.04")})
    with pytest.raises(ValidationError, match="Decimal"):
        FeeFill(
            fill_id="bad",
            price=0.71,
            quantity=Decimal("1"),
            notional=Decimal("0.71"),
            fee=Decimal("0.01"),
        )


def test_qualified_candidate_requires_rankable_market_and_complete_costs():
    candidate = ScanCandidate(
        market=_market(),
        quote=_quote(),
        fee_estimate=_fees(),
        assessment=_qualified(),
        consensus_probability=Decimal("0.78"),
        book_count=3,
        quantity=Decimal("2"),
        gross_edge=Decimal("0.07"),
        slippage=Decimal("0.01"),
        net_edge=Decimal("0.045"),
        expected_value=Decimal("0.09"),
        usable_liquidity=Decimal("10"),
        confidence=Decimal("0.90"),
        recommended_stake=Decimal("1.46"),
        maximum_acceptable_entry=Decimal("0.73"),
        policy_reference="scanner-policy-v1",
    )
    assert candidate.assessment.status is AssessmentStatus.QUALIFIED

    incomplete_market = PredictionMarket(
        identity=_instrument(),
        event=_event(),
        title="Incomplete market",
        status="open",
        closes_at=datetime(2026, 9, 23, tzinfo=UTC),
        resolution_rule=None,
        assessment=RecordAssessment(
            status=AssessmentStatus.MISSING_FIELDS,
            missing_fields=("resolution_rule",),
        ),
        raw=_raw(),
    )
    with pytest.raises(ValidationError, match="rankable market"):
        ScanCandidate(
            **{
                **candidate.model_dump(),
                "market": incomplete_market,
            }
        )
