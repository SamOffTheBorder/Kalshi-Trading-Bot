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

from kalshi_bot.strategy.levels import SpotBar


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

    # Recent underlying spot OHLCV bars, oldest first (tasks.md 6.1/6.2): the
    # trend/level strategies detect swing highs/lows and VWAP from this
    # series (strategy/levels.py). Empty for strategies that don't need bar
    # history (e.g. crypto_mispricing, which only looks at `spot`/`vol_annual`).
    spot_bars: tuple[SpotBar, ...] = field(default_factory=tuple)

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

    # P(this decision's own side wins) — side-consistent, in [0, 1]. For
    # BUY_YES this is P(YES resolves), for BUY_NO it is P(NO resolves) =
    # 1 - P(YES). Every BUY decision MUST set this; the engine sizes and
    # gates directly on it and does NOT invert or default it (kxbtc15m-
    # validation-rebuild §2.3: "no default certainty path"). A BUY that
    # leaves it None is dropped with a logged reason rather than treated as
    # a sure thing. HOLDs leave it None.
    fair_probability: float | None = None

    bs_probability: float | None = None
    mc_probability: float | None = None
    raw_edge: float | None = None
    fee_adjusted_edge: float | None = None
    confidence: float | None = None
    entry_price_cents: int | None = None  # the price this decision would pay
    hold_reason: str | None = None

    # Entry band, expressed as the range of contract prices (cents, treating
    # price as market-implied probability) this decision remains valid for.
    # None = no band declared (engine does not gate). A strategy that gates
    # on model probability, not price, should still declare this — it is
    # the invariant the engine checks the ACTUAL FILL against, since the
    # fill can land at a worse price than `entry_price_cents` (pessimistic
    # fills, or a fast-moving market between decision and fill). See
    # backtest-engine spec: "Entry gates are evaluated against the actual
    # fill." A fill outside this band is rejected rather than recorded.
    min_entry_price_cents: int | None = None
    max_entry_price_cents: int | None = None

    # Fixed-R exit levels (tasks.md 5.1/6.1/6.2, design D2/D3): the
    # underlying SPOT price (not contract cents) at which the strategy
    # considers the trade invalidated (stop) or its target reached (target).
    # None for strategies that don't use fixed-R exits (e.g. crypto_mispricing,
    # which holds to settlement). This is the strategy's own DIRECTIONAL
    # reasoning (spot terms, matching how it detected the level) — it is not
    # what BacktestEngine checks intrabar; see stop/target_price_cents below.
    stop_price: float | None = None
    target_price: float | None = None

    # Fixed-R exit levels, CONTRACT-CENTS terms (tasks.md 8.1's engine
    # extension). KXBTC15M markets are single-strike binaries, not a
    # continuously-spot-tracking instrument — converting a spot stop/target
    # into a contract-price trigger would require inverting the Black-
    # Scholes model, reintroducing exactly the zero-drift assumption design
    # D2 moved away from just to build an exit check. Instead, the engine
    # checks THESE fields directly against the market's own 1-minute
    # contract candles: exit as soon as the contract's own price crosses
    # `stop_price_cents` (against the position) or `target_price_cents`
    # (in favor). This matches what a real Kalshi exit order is keyed to
    # anyway. A strategy that only sets spot-terms stop_price/target_price
    # (not these) opts out of engine-level intrabar exit simulation.
    stop_price_cents: int | None = None
    target_price_cents: int | None = None


@runtime_checkable
class StrategyProtocol(Protocol):
    name: str

    def evaluate(self, context: StrategyContext) -> Decision: ...
