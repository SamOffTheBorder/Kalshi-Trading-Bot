"""Strategy protocol and shared types.

This module must never import from data clients, broker adapters, or the
execution layer: a strategy sees only its `StrategyContext` and returns a
`Decision`. That constraint is what lets the identical strategy object run
under the backtest engine, the paper loop, and (later) live trading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Action(StrEnum):
    BUY_YES = "BUY_YES"
    BUY_NO = "BUY_NO"
    HOLD = "HOLD"


@dataclass(frozen=True)
class StrategyContext:
    """Everything a strategy may look at for one evaluation. Assembled by the
    calling loop (backtest/paper/live) — strategies never fetch."""

    # market identity & structure
    market_ticker: str
    series_ticker: str
    strike_type: str  # greater | less | between
    floor_strike: float | None
    cap_strike: float | None

    # clocks (epoch seconds)
    now_ts: int
    close_ts: int

    # current quotes, integer cents (None = side unquoted)
    yes_bid_cents: int | None
    yes_ask_cents: int | None

    # inputs
    spot: float
    vol_annual: float
    vol_source: str

    # trend regime: signed z-score of the realized log-return over the caller's
    # lookback window, in units of what the zero-drift model expects (sigma*sqrt(t)).
    # None = not computable (insufficient spot history) -> no trend gate applied.
    trend_zscore: float | None = None

    # room for later signal inputs (sentiment, forecasts) without breaking the protocol
    extras: dict[str, float] = field(default_factory=dict)

    @property
    def t_years(self) -> float:
        return max(0.0, (self.close_ts - self.now_ts) / (365 * 24 * 3600))

    @property
    def minutes_to_expiry(self) -> float:
        return max(0.0, (self.close_ts - self.now_ts) / 60)


@dataclass(frozen=True)
class Decision:
    """Outcome of one evaluation. Every Decision — including HOLDs — is
    persisted to the audit trail by the calling loop."""

    action: Action
    market_ticker: str
    strategy_name: str

    bs_probability: float | None = None
    mc_probability: float | None = None
    raw_edge: float | None = None
    fee_adjusted_edge: float | None = None
    confidence: float | None = None
    entry_price_cents: int | None = None  # the price this decision would pay
    hold_reason: str | None = None


@runtime_checkable
class StrategyProtocol(Protocol):
    name: str

    def evaluate(self, context: StrategyContext) -> Decision: ...
