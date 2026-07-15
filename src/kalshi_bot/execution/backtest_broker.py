"""Simulated broker for historical replay — pessimistic by design.

Fill model (design decision 4): orders fill at the bar's WORST plausible
price for the side — buying YES pays the bar's highest ask; buying NO pays
100 minus the bar's lowest bid. A `midpoint` mode exists for sensitivity
analysis only. Kalshi's 7% fee on net winnings is applied inside settlement,
not as a reporting adjustment. Optimistic fill assumptions are the classic
way backtests lie; this one is built to understate, never overstate.

Positions are held to expiry and settled against the market's official
result — matching the Phase 1 strategy scope (entries only, no early exits).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Literal

from kalshi_bot.execution.broker_protocol import (
    MarketSnapshot,
    OrderRequest,
    OrderResult,
    Position,
)

KALSHI_FEE_RATE = 0.07

FillMode = Literal["pessimistic", "midpoint"]


@dataclass(frozen=True)
class MarketBar:
    """The slice of one candle the fill model needs, plus its timestamp."""

    market_ticker: str
    ts: int
    yes_bid_low: int | None
    yes_bid_close: int | None
    yes_ask_high: int | None
    yes_ask_close: int | None


@dataclass
class _OpenPosition:
    side: Literal["yes", "no"]
    quantity: int
    entry_price_cents: int
    entry_ts: int


@dataclass(frozen=True)
class Settlement:
    market_ticker: str
    side: Literal["yes", "no"]
    quantity: int
    entry_price_cents: int
    entry_ts: int
    won: bool
    gross_pnl_usd: float
    fee_usd: float
    net_pnl_usd: float
    settled_ts: int


class BacktestBroker:
    """Implements BrokerAdapter against replayed historical bars."""

    def __init__(self, *, starting_cash_usd: float, fill_mode: FillMode = "pessimistic") -> None:
        self._cash = starting_cash_usd
        self._fill_mode: FillMode = fill_mode
        self._positions: dict[str, _OpenPosition] = {}
        self._current_bars: dict[str, MarketBar] = {}
        self._order_ids = itertools.count(1)
        self.settlements: list[Settlement] = []

    # -- engine-facing (not part of BrokerAdapter) ------------------------------

    def set_current_bar(self, bar: MarketBar) -> None:
        """Engine calls this as it steps through history."""
        self._current_bars[bar.market_ticker] = bar

    def settle_market(self, market_ticker: str, result: str, settled_ts: int) -> None:
        """Settle any open position against the official result. Fee on wins."""
        pos = self._positions.pop(market_ticker, None)
        if pos is None:
            return
        cost_dollars = pos.entry_price_cents / 100
        won = pos.side == result
        if won:
            gross = (1.0 - cost_dollars) * pos.quantity
            fee = gross * KALSHI_FEE_RATE
            self._cash += pos.quantity * 1.0 - fee  # stake back + net winnings
        else:
            gross = -cost_dollars * pos.quantity
            fee = 0.0
        self.settlements.append(
            Settlement(
                market_ticker=market_ticker,
                side=pos.side,
                quantity=pos.quantity,
                entry_price_cents=pos.entry_price_cents,
                entry_ts=pos.entry_ts,
                won=won,
                gross_pnl_usd=gross,
                fee_usd=fee,
                net_pnl_usd=gross - fee,
                settled_ts=settled_ts,
            )
        )

    # -- fill model ------------------------------------------------------------

    def _fill_price_cents(self, bar: MarketBar, side: str) -> int | None:
        if side == "yes":
            if self._fill_mode == "pessimistic":
                return bar.yes_ask_high
            if bar.yes_ask_close is None or bar.yes_bid_close is None:
                return None
            return round((bar.yes_ask_close + bar.yes_bid_close) / 2)
        # NO side: price = 100 - yes_bid; worst = lowest bid
        if self._fill_mode == "pessimistic":
            return None if bar.yes_bid_low is None else 100 - bar.yes_bid_low
        if bar.yes_ask_close is None or bar.yes_bid_close is None:
            return None
        return 100 - round((bar.yes_bid_close + bar.yes_ask_close) / 2)

    # -- BrokerAdapter -------------------------------------------------------------

    @property
    def broker_name(self) -> str:
        return "backtest"

    async def get_account_balance(self) -> float:
        return self._cash

    async def get_open_positions(self) -> list[Position]:
        return [
            Position(
                market_ticker=ticker,
                side=pos.side,
                quantity=pos.quantity,
                avg_entry_price_cents=float(pos.entry_price_cents),
            )
            for ticker, pos in self._positions.items()
        ]

    async def place_order(self, order: OrderRequest) -> OrderResult:
        order_id = f"bt-{next(self._order_ids)}"

        def reject(reason: str) -> OrderResult:
            return OrderResult(
                order_id=order_id,
                market_ticker=order.market_ticker,
                side=order.side,
                status="rejected",
                reject_reason=reason,
            )

        bar = self._current_bars.get(order.market_ticker)
        if bar is None:
            return reject("no_market_data")
        if order.market_ticker in self._positions:
            return reject("position_already_open")

        price_cents = self._fill_price_cents(bar, order.side)
        if price_cents is None or not 1 <= price_cents <= 99:
            return reject("no_fillable_quote")
        if order.limit_price_cents is not None and price_cents > order.limit_price_cents:
            return reject("limit_exceeded")

        cost = (price_cents / 100) * order.quantity
        if cost > self._cash:
            return reject("insufficient_funds")

        self._cash -= cost
        self._positions[order.market_ticker] = _OpenPosition(
            side=order.side,
            quantity=order.quantity,
            entry_price_cents=price_cents,
            entry_ts=bar.ts,
        )
        return OrderResult(
            order_id=order_id,
            market_ticker=order.market_ticker,
            side=order.side,
            status="filled",
            quantity=order.quantity,
            fill_price_cents=price_cents,
            filled_at_ts=bar.ts,
        )

    async def cancel_order(self, order_id: str) -> None:
        return None  # fills are immediate in replay; nothing rests

    async def get_market_snapshot(self, instrument_id: str) -> MarketSnapshot:
        bar = self._current_bars.get(instrument_id)
        if bar is None:
            return MarketSnapshot(
                market_ticker=instrument_id, ts=0, yes_bid_cents=None, yes_ask_cents=None
            )
        return MarketSnapshot(
            market_ticker=instrument_id,
            ts=bar.ts,
            yes_bid_cents=bar.yes_bid_close,
            yes_ask_cents=bar.yes_ask_close,
        )
