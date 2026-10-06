"""Venue-neutral research contracts.

These contracts deliberately do not expose broker, account, or order APIs.
"""

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
    OrderBookSnapshot,
    PredictionEvent,
    PredictionMarket,
    RawMarketRecord,
    RecordAssessment,
    ScanCandidate,
    Venue,
)

__all__ = [
    "AssessmentStatus",
    "ContractSide",
    "EventIdentity",
    "FeeAggregationScope",
    "FeeEstimate",
    "FeeFill",
    "FeeSchedule",
    "InstrumentIdentity",
    "MarketQuote",
    "OrderBookSnapshot",
    "PredictionEvent",
    "PredictionMarket",
    "RawMarketRecord",
    "RecordAssessment",
    "ScanCandidate",
    "Venue",
]
