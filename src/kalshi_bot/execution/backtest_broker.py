"""Simulated broker for historical replay — pessimistic by design.

Fill model (design decision 4): orders fill at the bar's WORST plausible
price for the side — buying YES pays the bar's highest ask; buying NO pays
100 minus the bar's lowest bid. A `midpoint` mode exists for sensitivity
analysis only. Optimistic fill assumptions are the classic way backtests
lie; this one is built to understate, never overstate.

Fee model (corrected, v2 — see signals/fees.py): Kalshi charges
`ceil(coef * P * (1-P) * n * 100) / 100` dollars, **at entry, win or lose**.
There is no settlement fee. Default execution is "taker" (crosses the
spread, pessimistic fill = worst plausible price, taker coefficient 0.07).
`OrderRequest.execution_style="maker"` (task 3.4) instead rests at the
order's own `limit_price_cents` and fills only if the bar shows the OTHER
side of the book traded through that level — proof a counterparty existed —
at the maker coefficient (0.0175, ~1/4 of taker). A maker order that isn't
touched is rejected, not partially filled or repriced.

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
from kalshi_bot.signals.fees import MAKER_FEE_COEFFICIENT, TAKER_FEE_COEFFICIENT, entry_fee_dollars

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
    volume: int | None = None  # contracts traded in this bar; None = unknown (no cap)
    # Needed only for maker (resting) fills — did the OTHER side of the book
    # trade far enough to have hit a resting order at the requested price.
    yes_bid_high: int | None = None
    yes_ask_low: int | None = None


@dataclass
class _OpenPosition:
    side: Literal["yes", "no"]
    quantity: int
    entry_price_cents: int
    entry_ts: int
    entry_fee_usd: float  # paid at entry, win or lose — see signals/fees.py


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

    def __init__(
        self,
        *,
        starting_cash_usd: float,
        fill_mode: FillMode = "pessimistic",
        liquidity_cap_frac: float = 0.25,
    ) -> None:
        """`liquidity_cap_frac`: max fraction of a bar's traded volume one order
        may fill (partial fill beyond it, reject if the cap rounds to zero).
        Run #7 exposed why: Kelly compounding grew fills past entire markets'
        LIFETIME volume, producing fantasy PnL. Applies only when the bar
        carries a volume figure."""
        if not 0 < liquidity_cap_frac <= 1:
            raise ValueError("liquidity_cap_frac must be in (0, 1]")
        self._cash = starting_cash_usd
        self._fill_mode: FillMode = fill_mode
        self._liquidity_cap_frac = liquidity_cap_frac
        self._positions: dict[str, _OpenPosition] = {}
        self._current_bars: dict[str, MarketBar] = {}
        self._order_ids = itertools.count(1)
        self.settlements: list[Settlement] = []

    # -- engine-facing (not part of BrokerAdapter) ------------------------------

    def set_current_bar(self, bar: MarketBar) -> None:
        """Engine calls this as it steps through history."""
        self._current_bars[bar.market_ticker] = bar

    def void_fill(self, market_ticker: str) -> None:
        """Undo an immediately-preceding `place_order` fill for `market_ticker`
        as if it never happened: refunds stake + fee, drops the position.

        Engine-only escape hatch for the entry-gate-vs-actual-fill check
        (spec: backtest-engine "Entry gates are evaluated against the actual
        fill") — replay fills are immediate (no resting order to cancel via
        `cancel_order`), so a fill that lands outside the strategy's entry
        band is placed, inspected, and then voided here rather than never
        placed at all. No-op if there is no open position for the ticker.
        """
        pos = self._positions.pop(market_ticker, None)
        if pos is None:
            return
        stake = (pos.entry_price_cents / 100) * pos.quantity
        self._cash += stake + pos.entry_fee_usd

    def close_position_early(
        self, market_ticker: str, exit_price_cents: int, exit_ts: int
    ) -> Settlement | None:
        """Close an open position before market settlement at a specific
        contract price — the fixed-R stop/target exit path (tasks.md 6.1/6.2
        + 8.1's engine extension), as distinct from `settle_market`'s
        hold-to-expiry path. Charges no additional fee: Kalshi's fee is
        entry-only (signals/fees.py), same accounting as `settle_market`.
        No-op (returns None) if there is no open position for the ticker —
        the engine may call this defensively without checking first."""
        pos = self._positions.pop(market_ticker, None)
        if pos is None:
            return None
        entry_cost = pos.entry_price_cents / 100
        exit_value = exit_price_cents / 100
        if pos.side == "yes":
            # Sold at exit_value/contract: proceeds = exit_value * quantity.
            won = exit_price_cents > pos.entry_price_cents
            gross = (exit_value - entry_cost) * pos.quantity
            proceeds = exit_value * pos.quantity
        else:
            # A NO position's contract price is (1 - yes_price); "selling"
            # it back means receiving (1 - exit_value) per contract.
            won = exit_price_cents < pos.entry_price_cents
            gross = (entry_cost - exit_value) * pos.quantity
            proceeds = (1.0 - exit_value) * pos.quantity
        self._cash += proceeds
        settlement = Settlement(
            market_ticker=market_ticker,
            side=pos.side,
            quantity=pos.quantity,
            entry_price_cents=pos.entry_price_cents,
            entry_ts=pos.entry_ts,
            won=won,
            gross_pnl_usd=gross,
            fee_usd=pos.entry_fee_usd,
            net_pnl_usd=gross - pos.entry_fee_usd,
            settled_ts=exit_ts,
        )
        self.settlements.append(settlement)
        return settlement

    def settle_market(self, market_ticker: str, result: str, settled_ts: int) -> None:
        """Settle any open position against the official result.

        No fee is charged here — the entry fee was already paid (and already
        deducted from cash) in `place_order`, win or lose. Settlement only
        returns the stake/payout.
        """
        pos = self._positions.pop(market_ticker, None)
        if pos is None:
            return
        cost_dollars = pos.entry_price_cents / 100
        won = pos.side == result
        if won:
            gross = (1.0 - cost_dollars) * pos.quantity
            self._cash += pos.quantity * 1.0  # stake back + winnings, no settlement fee
        else:
            gross = -cost_dollars * pos.quantity
        self.settlements.append(
            Settlement(
                market_ticker=market_ticker,
                side=pos.side,
                quantity=pos.quantity,
                entry_price_cents=pos.entry_price_cents,
                entry_ts=pos.entry_ts,
                won=won,
                gross_pnl_usd=gross,
                fee_usd=pos.entry_fee_usd,
                net_pnl_usd=gross - pos.entry_fee_usd,
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

    def _maker_fill_price_cents(
        self, bar: MarketBar, side: str, limit_price_cents: int
    ) -> int | None:
        """A resting (maker) order fills at exactly the requested limit price
        — never worse, that's the point of resting — but only if the OTHER
        side of the book traded through that level at some point in the bar,
        proving a counterparty existed to cross it. No such evidence -> no
        fill (pessimistic about maker fills too: we do not assume a passive
        order gets picked off just because it was posted).

        YES buy resting at L: fills iff the ask traded down to L or below
        at some point (bar.yes_ask_low <= L) — someone sold into the resting bid.
        NO buy resting at L (NO price = 100 - yes_bid): fills iff the bid
        traded up to (100 - L) or above (bar.yes_bid_high >= 100 - L) —
        someone bought YES aggressively enough to lift the bid to where a
        resting NO order at L would cross.
        """
        if side == "yes":
            if bar.yes_ask_low is None or bar.yes_ask_low > limit_price_cents:
                return None
            return limit_price_cents
        if bar.yes_bid_high is None or bar.yes_bid_high < 100 - limit_price_cents:
            return None
        return limit_price_cents

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

        if order.execution_style == "maker":
            if order.limit_price_cents is None:
                return reject("maker_requires_limit_price")
            price_cents = self._maker_fill_price_cents(bar, order.side, order.limit_price_cents)
            fee_coefficient = MAKER_FEE_COEFFICIENT
            if price_cents is None:
                return reject("resting_order_not_touched")
        else:
            price_cents = self._fill_price_cents(bar, order.side)
            fee_coefficient = TAKER_FEE_COEFFICIENT
            if price_cents is None or not 1 <= price_cents <= 99:
                return reject("no_fillable_quote")
            if order.limit_price_cents is not None and price_cents > order.limit_price_cents:
                return reject("limit_exceeded")

        quantity = order.quantity
        if bar.volume is not None:
            max_fillable = int(bar.volume * self._liquidity_cap_frac)
            if max_fillable < 1:
                return reject("insufficient_liquidity")
            quantity = min(quantity, max_fillable)

        stake = (price_cents / 100) * quantity
        fee = entry_fee_dollars(price_cents, quantity, coefficient=fee_coefficient)
        cost = stake + fee
        if cost > self._cash:
            return reject("insufficient_funds")

        self._cash -= cost
        self._positions[order.market_ticker] = _OpenPosition(
            side=order.side,
            quantity=quantity,
            entry_price_cents=price_cents,
            entry_ts=bar.ts,
            entry_fee_usd=fee,
        )
        return OrderResult(
            order_id=order_id,
            market_ticker=order.market_ticker,
            side=order.side,
            status="filled",
            quantity=quantity,
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
