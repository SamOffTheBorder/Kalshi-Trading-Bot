"""Read-only, venue-neutral prediction-market data boundary.

This protocol is deliberately separate from execution brokers.  Adapters expose
only public research data, declare each operation they implement, and return an
explicit unsupported result when an optional capability is unavailable.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from kalshi_bot.domain.prediction import (
    InstrumentIdentity,
    MarketQuote,
    OrderBookSnapshot,
    PredictionEvent,
    PredictionMarket,
    Venue,
)


class MarketDataCapability(StrEnum):
    LIST_SPORTS = "list_sports"
    LIST_LEAGUES = "list_leagues"
    LIST_EVENTS = "list_events"
    LIST_MARKETS = "list_markets"
    MARKET_DETAIL = "get_market"
    BBO = "get_bbo"
    ORDER_BOOK = "get_order_book"
    PRICE_HISTORY = "get_price_history"
    QUOTE_STREAM = "stream_quotes"


@dataclass(frozen=True, slots=True)
class MarketDataCapabilities:
    """The complete set of operations an adapter claims to support."""

    supported: frozenset[MarketDataCapability]

    def supports(self, capability: MarketDataCapability) -> bool:
        return capability in self.supported


@dataclass(frozen=True, slots=True)
class UnsupportedCapability:
    capability: MarketDataCapability
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("unsupported capability reason must not be empty")


@dataclass(frozen=True, slots=True)
class MarketDataResult[ResultValue]:
    """Either canonical data or an explicit unsupported-capability outcome."""

    value: ResultValue | None = None
    unsupported: UnsupportedCapability | None = None

    def __post_init__(self) -> None:
        if (self.value is None) == (self.unsupported is None):
            raise ValueError("result must contain exactly one of value or unsupported")

    @property
    def is_supported(self) -> bool:
        return self.unsupported is None

    @classmethod
    def success(cls, value: ResultValue) -> MarketDataResult[ResultValue]:
        return cls(value=value)

    @classmethod
    def not_supported(
        cls,
        capability: MarketDataCapability,
        *,
        reason: str,
    ) -> MarketDataResult[ResultValue]:
        return cls(unsupported=UnsupportedCapability(capability=capability, reason=reason))


@runtime_checkable
class MarketDataAdapter(Protocol):
    """Canonical read-only market-data operations; never an execution API."""

    @property
    def venue(self) -> Venue: ...

    @property
    def capabilities(self) -> MarketDataCapabilities: ...

    def list_sports(self) -> MarketDataResult[tuple[str, ...]]: ...

    def list_leagues(self, *, sport: str | None = None) -> MarketDataResult[tuple[str, ...]]: ...

    def list_events(
        self,
        *,
        sport: str | None = None,
        league: str | None = None,
        starts_after: datetime | None = None,
        starts_before: datetime | None = None,
    ) -> MarketDataResult[tuple[PredictionEvent, ...]]: ...

    def list_markets(
        self,
        *,
        event_id: str | None = None,
    ) -> MarketDataResult[tuple[PredictionMarket, ...]]: ...

    def get_market(
        self,
        instrument: InstrumentIdentity,
    ) -> MarketDataResult[PredictionMarket]: ...

    def get_bbo(self, instrument: InstrumentIdentity) -> MarketDataResult[MarketQuote]: ...

    def get_order_book(
        self,
        instrument: InstrumentIdentity,
    ) -> MarketDataResult[OrderBookSnapshot]: ...

    def get_price_history(
        self,
        instrument: InstrumentIdentity,
        *,
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
    ) -> MarketDataResult[tuple[MarketQuote, ...]]: ...

    def stream_quotes(
        self,
        instruments: tuple[InstrumentIdentity, ...],
    ) -> MarketDataResult[Iterable[MarketQuote]]: ...


__all__ = [
    "MarketDataAdapter",
    "MarketDataCapabilities",
    "MarketDataCapability",
    "MarketDataResult",
    "UnsupportedCapability",
]
