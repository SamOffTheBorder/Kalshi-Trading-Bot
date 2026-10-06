"""Immutable venue-neutral contracts for read-only prediction-market research."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Venue(StrEnum):
    KALSHI = "kalshi"
    POLYMARKET_US = "polymarket_us"


class ContractSide(StrEnum):
    YES = "yes"
    NO = "no"


class AssessmentStatus(StrEnum):
    """Outcome of normalizing or qualifying a research record."""

    QUALIFIED = "qualified"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"
    MISSING_FIELDS = "missing_fields"


class FeeAggregationScope(StrEnum):
    """Scope at which a venue rounds and aggregates taker fees."""

    FILL = "fill"
    CUMULATIVE_ORDER = "cumulative_order"


class RecordAssessment(ContractModel):
    status: AssessmentStatus
    reason_codes: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    unsupported_fields: tuple[str, ...] = ()

    @field_validator("reason_codes", "missing_fields", "unsupported_fields")
    @classmethod
    def _unique_nonempty_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item for item in value):
            raise ValueError("assessment values must be nonempty")
        if len(value) != len(set(value)):
            raise ValueError("assessment values must be unique")
        return value

    @model_validator(mode="after")
    def _status_has_evidence(self) -> RecordAssessment:
        if self.status is AssessmentStatus.QUALIFIED:
            if self.reason_codes or self.missing_fields or self.unsupported_fields:
                raise ValueError("qualified assessment cannot contain failure evidence")
        elif self.status is AssessmentStatus.MISSING_FIELDS and not self.missing_fields:
            raise ValueError("missing_fields assessment must identify missing fields")
        elif self.status is AssessmentStatus.UNSUPPORTED and not (
            self.unsupported_fields or self.reason_codes
        ):
            raise ValueError("unsupported assessment must identify unsupported data")
        elif self.status is AssessmentStatus.REJECTED and not self.reason_codes:
            raise ValueError("rejected assessment must include a reason code")
        return self


class ExternalIdentity(ContractModel):
    venue: Venue
    external_id: str = Field(min_length=1)


class EventIdentity(ExternalIdentity):
    canonical_id: str = Field(min_length=1)
    real_world_event_id: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _distinct_aliases(self) -> EventIdentity:
        if len(self.aliases) != len(set(self.aliases)):
            raise ValueError("event aliases must be unique")
        return self


class InstrumentIdentity(ExternalIdentity):
    canonical_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    side: ContractSide


class RawReference(ContractModel):
    source: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    locator: str | None = Field(default=None, min_length=1)


class ResolutionRule(ContractModel):
    text: str = Field(min_length=1)
    source: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    outcome_orientation: str | None = Field(default=None, min_length=1)


class RawMarketRecord(ContractModel):
    """Auditable envelope for a market row that could not be fully normalized."""

    venue: Venue
    event_external_id: str | None = Field(default=None, min_length=1)
    market_external_id: str | None = Field(default=None, min_length=1)
    side: ContractSide | None = None
    resolution_rule: ResolutionRule | None = None
    assessment: RecordAssessment
    raw: RawReference

    @model_validator(mode="after")
    def _missing_data_is_explicit(self) -> RawMarketRecord:
        missing: set[str] = set()
        if self.event_external_id is None:
            missing.add("event_external_id")
        if self.market_external_id is None:
            missing.add("market_external_id")
        if self.side is None:
            missing.add("side")
        if self.resolution_rule is None:
            missing.add("resolution_rule")
        elif self.resolution_rule.outcome_orientation is None:
            missing.add("resolution_rule.outcome_orientation")

        declared = set(self.assessment.missing_fields)
        if missing and self.assessment.status is not AssessmentStatus.MISSING_FIELDS:
            raise ValueError("incomplete raw market must have missing_fields status")
        if not missing.issubset(declared):
            raise ValueError("raw market assessment must declare every missing field")
        return self


class PredictionEvent(ContractModel):
    identity: EventIdentity
    sport: str = Field(min_length=1)
    league: str = Field(min_length=1)
    participants: tuple[str, ...] = Field(min_length=2)
    starts_at: datetime
    status: str = Field(min_length=1)
    raw: RawReference

    @field_validator("starts_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)


class PredictionMarket(ContractModel):
    identity: InstrumentIdentity
    event: PredictionEvent
    title: str = Field(min_length=1)
    status: str = Field(min_length=1)
    closes_at: datetime
    resolution_rule: ResolutionRule | None = None
    assessment: RecordAssessment
    raw: RawReference

    @field_validator("closes_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _assessment_matches_settlement_metadata(self) -> PredictionMarket:
        missing: set[str] = set()
        if self.resolution_rule is None:
            missing.add("resolution_rule")
        elif self.resolution_rule.outcome_orientation is None:
            missing.add("resolution_rule.outcome_orientation")

        if missing:
            if self.assessment.status is not AssessmentStatus.MISSING_FIELDS:
                raise ValueError("market with incomplete settlement metadata cannot qualify")
            if not missing.issubset(set(self.assessment.missing_fields)):
                raise ValueError("market assessment must declare missing settlement metadata")
        return self

    @property
    def rankable(self) -> bool:
        return (
            self.assessment.status is AssessmentStatus.QUALIFIED
            and self.resolution_rule is not None
            and bool(self.resolution_rule.outcome_orientation)
        )


class MarketQuote(ContractModel):
    instrument: InstrumentIdentity
    bid: Decimal | None = Field(default=None, ge=0)
    ask: Decimal | None = Field(default=None, ge=0)
    bid_quantity: Decimal | None = Field(default=None, ge=0)
    ask_quantity: Decimal | None = Field(default=None, ge=0)
    payout: Decimal = Field(gt=0)
    tick_size: Decimal = Field(gt=0)
    quantity_step: Decimal = Field(gt=0)
    minimum_quantity: Decimal = Field(gt=0)
    currency: str = Field(default="USD", min_length=1)
    source_at: datetime
    observed_at: datetime
    available_at: datetime
    retrieved_at: datetime
    raw: RawReference

    @field_validator(
        "bid",
        "ask",
        "bid_quantity",
        "ask_quantity",
        "payout",
        "tick_size",
        "quantity_step",
        "minimum_quantity",
        mode="before",
    )
    @classmethod
    def _decimal_only(cls, value: object) -> object:
        if value is not None and not isinstance(value, Decimal):
            raise ValueError("monetary and quantity values must be Decimal")
        return value

    @field_validator("source_at", "observed_at", "available_at", "retrieved_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _causal_times(self) -> MarketQuote:
        if self.available_at < self.observed_at or self.retrieved_at < self.available_at:
            raise ValueError("quote timestamps must be causally ordered")
        return self


class OrderBookLevel(ContractModel):
    price: Decimal = Field(ge=0)
    quantity: Decimal = Field(gt=0)

    @field_validator("price", "quantity", mode="before")
    @classmethod
    def _decimal_only(cls, value: object) -> object:
        if not isinstance(value, Decimal):
            raise ValueError("book values must be Decimal")
        return value


class OrderBookSnapshot(ContractModel):
    instrument: InstrumentIdentity
    bids: tuple[OrderBookLevel, ...] = ()
    asks: tuple[OrderBookLevel, ...] = ()
    source_at: datetime
    observed_at: datetime
    available_at: datetime
    retrieved_at: datetime
    raw: RawReference

    @field_validator("source_at", "observed_at", "available_at", "retrieved_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _causal_times(self) -> OrderBookSnapshot:
        if self.available_at < self.observed_at or self.retrieved_at < self.available_at:
            raise ValueError("book timestamps must be causally ordered")
        return self


class FeeSchedule(ContractModel):
    """Versioned fee inputs; venue-specific arithmetic lives outside this contract."""

    venue: Venue
    coefficient: Decimal = Field(ge=0)
    effective_date: date
    source: str = Field(min_length=1)
    formula_version: str = Field(min_length=1)
    rounding_version: str = Field(min_length=1)
    aggregation_scope: FeeAggregationScope
    verified_at: datetime

    @field_validator("coefficient", mode="before")
    @classmethod
    def _decimal_only(cls, value: object) -> object:
        if not isinstance(value, Decimal):
            raise ValueError("fee coefficient must be Decimal")
        return value

    @field_validator("verified_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)


class FeeFill(ContractModel):
    fill_id: str = Field(min_length=1)
    price: Decimal = Field(ge=0, le=1)
    quantity: Decimal = Field(gt=0)
    notional: Decimal = Field(ge=0)
    fee: Decimal = Field(ge=0)

    @field_validator("price", "quantity", "notional", "fee", mode="before")
    @classmethod
    def _decimal_only(cls, value: object) -> object:
        if not isinstance(value, Decimal):
            raise ValueError("fee values must be Decimal")
        return value

    @model_validator(mode="after")
    def _notional_matches_fill(self) -> FeeFill:
        if self.notional != self.price * self.quantity:
            raise ValueError("fill notional must equal price times quantity")
        return self


class FeeEstimate(ContractModel):
    instrument: InstrumentIdentity
    schedule: FeeSchedule
    fills: tuple[FeeFill, ...] = Field(min_length=1)
    total_quantity: Decimal = Field(gt=0)
    total_notional: Decimal = Field(ge=0)
    total_fee: Decimal = Field(ge=0)
    currency: str = Field(default="USD", min_length=1)
    calculated_at: datetime

    @field_validator("total_quantity", "total_notional", "total_fee", mode="before")
    @classmethod
    def _decimal_only(cls, value: object) -> object:
        if not isinstance(value, Decimal):
            raise ValueError("fee totals must be Decimal")
        return value

    @field_validator("calculated_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _totals_match_fills(self) -> FeeEstimate:
        if self.schedule.venue is not self.instrument.venue:
            raise ValueError("fee schedule venue must match instrument venue")
        if self.total_quantity != sum((fill.quantity for fill in self.fills), Decimal(0)):
            raise ValueError("total quantity must equal fill quantities")
        if self.total_notional != sum((fill.notional for fill in self.fills), Decimal(0)):
            raise ValueError("total notional must equal fill notionals")
        if self.total_fee != sum((fill.fee for fill in self.fills), Decimal(0)):
            raise ValueError("total fee must equal fill fees")
        return self


class ScanCandidate(ContractModel):
    """Deterministic research result with no execution authority."""

    market: PredictionMarket
    quote: MarketQuote | None = None
    fee_estimate: FeeEstimate | None = None
    assessment: RecordAssessment
    market_url: str | None = Field(default=None, min_length=1)
    consensus_probability: Decimal | None = Field(default=None, ge=0, le=1)
    book_count: int | None = Field(default=None, ge=0)
    quantity: Decimal | None = Field(default=None, gt=0)
    gross_edge: Decimal | None = None
    slippage: Decimal | None = Field(default=None, ge=0)
    net_edge: Decimal | None = None
    expected_value: Decimal | None = None
    usable_liquidity: Decimal | None = Field(default=None, ge=0)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    recommended_stake: Decimal | None = Field(default=None, ge=0)
    maximum_acceptable_entry: Decimal | None = Field(default=None, ge=0, le=1)
    reasons: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    input_references: tuple[str, ...] = ()
    policy_reference: str | None = Field(default=None, min_length=1)

    @field_validator(
        "consensus_probability",
        "quantity",
        "gross_edge",
        "slippage",
        "net_edge",
        "expected_value",
        "usable_liquidity",
        "confidence",
        "recommended_stake",
        "maximum_acceptable_entry",
        mode="before",
    )
    @classmethod
    def _decimal_only(cls, value: object) -> object:
        if value is not None and not isinstance(value, Decimal):
            raise ValueError("candidate numeric values must be Decimal")
        return value

    @model_validator(mode="after")
    def _qualified_candidate_is_complete(self) -> ScanCandidate:
        if self.assessment.status is not AssessmentStatus.QUALIFIED:
            return self
        if not self.market.rankable:
            raise ValueError("qualified candidate requires a rankable market")
        if self.quote is None or self.quote.ask is None:
            raise ValueError("qualified candidate requires an executable ask")
        if self.quote.instrument != self.market.identity:
            raise ValueError("candidate quote instrument must match market")
        if self.fee_estimate is None or self.fee_estimate.instrument != self.market.identity:
            raise ValueError("qualified candidate requires a matching fee estimate")

        required = {
            "consensus_probability": self.consensus_probability,
            "book_count": self.book_count,
            "quantity": self.quantity,
            "gross_edge": self.gross_edge,
            "slippage": self.slippage,
            "net_edge": self.net_edge,
            "expected_value": self.expected_value,
            "usable_liquidity": self.usable_liquidity,
            "confidence": self.confidence,
            "recommended_stake": self.recommended_stake,
            "maximum_acceptable_entry": self.maximum_acceptable_entry,
            "policy_reference": self.policy_reference,
        }
        missing = sorted(name for name, value in required.items() if value is None)
        if missing:
            raise ValueError(f"qualified candidate missing fields: {', '.join(missing)}")
        return self


__all__ = [
    "AssessmentStatus",
    "ContractSide",
    "EventIdentity",
    "ExternalIdentity",
    "FeeAggregationScope",
    "FeeEstimate",
    "FeeFill",
    "FeeSchedule",
    "InstrumentIdentity",
    "MarketQuote",
    "OrderBookLevel",
    "OrderBookSnapshot",
    "PredictionEvent",
    "PredictionMarket",
    "RawMarketRecord",
    "RawReference",
    "RecordAssessment",
    "ResolutionRule",
    "ScanCandidate",
    "Venue",
]
