"""Paper broker: `BrokerAdapter` over LIVE quotes, simulated fills, real
persistence (paper-trading-and-notify tasks.md §2.1).

Unlike `BacktestBroker`, which replays historical bars, this broker is fed
one live `MarketSnapshot` per market per loop tick (the caller polls Kalshi;
see `scripts/run_paper_trading.py`). No real order ever reaches Kalshi — an
order "fills" against the live quote the caller just observed, at the same
side-aware worst-of-the-quote convention `BacktestBroker` uses (buying YES
pays the ask; buying NO pays `100 - yes_bid`), so paper PnL is not flattered
relative to what a real marketable order would have paid.

**Every order is a limit order — `place_order` requires
`OrderRequest.limit_price_cents` and rejects `reject_reason=
"limit_price_required"` if it is missing.** There is no quick/market-buy
path (operator decision): the strategy already computed its edge assuming
it pays a specific price (`Decision.entry_price_cents`), and the broker must
never fill worse than that. This is a MARKETABLE limit — it still fills
immediately when the current quote is at or better than the limit — not a
resting order; `execution_style="maker"` (a truly resting order) is still
rejected below for the same reason `BacktestBroker` rejects it: no validated
model exists for inferring a resting fill from a single point-in-time quote.

Every fill and settlement is written straight to `SimulatedTrade` with
`mode="paper"` — the schema of record the dashboard already reads, so paper
trades show up in the same equity curve and run views as backtest runs
(distinguished by `mode`, not a separate table).

Fee model matches `BacktestBroker`/`signals/fees.py` exactly: taker fee at
entry, win or lose; a second taker fee on an early close; no settlement fee.
Positions restore from `SimulatedTrade` rows with `status="open"` on
construction (§2.2 orphan-position recovery) — a restarted loop does not
forget what it already holds.
"""

from __future__ import annotations

import itertools
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.execution.broker_protocol import (
    MarketSnapshot,
    OrderRequest,
    OrderResult,
    Position,
)
from kalshi_bot.signals.fees import TAKER_FEE_COEFFICIENT, entry_fee_dollars
from kalshi_bot.storage.models import SimulatedTrade


class PaperBroker:
    """Implements BrokerAdapter against live-polled quotes.

    `set_current_quote` must be called with each market's latest snapshot
    before `place_order`/`get_market_snapshot` are used for that market in
    a given loop tick — the same "engine feeds the broker a bar" shape as
    `BacktestBroker.set_current_bar`, just fed from a live poll instead of
    replay.
    """

    def __init__(
        self,
        session: Session,
        *,
        starting_cash_usd: float,
    ) -> None:
        self._session = session
        self._quotes: dict[str, MarketSnapshot] = {}
        self._order_ids = itertools.count(1)
        self._positions: dict[str, SimulatedTrade] = {}
        self._cash = starting_cash_usd
        self._restore_open_positions()

    # -- restart recovery (§2.2) ------------------------------------------

    def _restore_open_positions(self) -> None:
        """Reload open paper positions from storage and rebuild cash from
        the full paper trade history, so a restarted loop resumes exactly
        where it left off rather than starting from a fresh bankroll while
        still holding (or forgetting) live positions."""
        rows = list(
            self._session.execute(
                select(SimulatedTrade).where(SimulatedTrade.mode == "paper")
            ).scalars()
        )
        for row in rows:
            if row.status == "open":
                self._positions[row.market_ticker] = row
                stake = (row.entry_price_cents / 100) * row.quantity
                self._cash -= stake + (row.entry_fee_usd or 0.0)
            else:
                self._cash += row.net_pnl_usd or 0.0

    # -- caller-facing (not part of BrokerAdapter) -------------------------

    def set_current_quote(self, snapshot: MarketSnapshot) -> None:
        self._quotes[snapshot.market_ticker] = snapshot

    def settle_market(self, market_ticker: str, result: str, settled_ts: int) -> float | None:
        """Settle an open paper position against the official market result.
        No fee here — the entry fee was already paid at open, win or lose.
        Returns the realized net PnL (so a caller can feed
        `EmergencyControl.record_trade_pnl`), or None if there was nothing
        open for this ticker."""
        row = self._positions.pop(market_ticker, None)
        if row is None:
            return None
        cost_dollars = row.entry_price_cents / 100
        won = row.side == result
        if won:
            gross = (1.0 - cost_dollars) * row.quantity
            self._cash += row.quantity * 1.0
        else:
            gross = -cost_dollars * row.quantity
        row.exit_ts = settled_ts
        row.exit_price_cents = 100 if won else 0
        row.status = "settled_won" if won else "settled_lost"
        row.gross_pnl_usd = gross
        row.exit_fee_usd = 0.0
        row.net_pnl_usd = gross - (row.entry_fee_usd or 0.0)
        self._session.add(row)
        return row.net_pnl_usd

    def open_position_tickers(self) -> list[str]:
        return list(self._positions.keys())

    # -- BrokerAdapter ------------------------------------------------------

    @property
    def broker_name(self) -> str:
        return "paper"

    async def get_account_balance(self) -> float:
        return self._cash

    async def get_open_positions(self) -> list[Position]:
        return [
            Position(
                market_ticker=row.market_ticker,
                side=row.side,
                quantity=int(row.quantity),
                avg_entry_price_cents=float(row.entry_price_cents),
            )
            for row in self._positions.values()
        ]

    async def place_order(self, order: OrderRequest) -> OrderResult:
        order_id = f"paper-{next(self._order_ids)}"

        def reject(reason: str) -> OrderResult:
            return OrderResult(
                order_id=order_id,
                market_ticker=order.market_ticker,
                side=order.side,
                status="rejected",
                reject_reason=reason,
            )

        snapshot = self._quotes.get(order.market_ticker)
        if snapshot is None:
            return reject("no_market_data")
        if order.market_ticker in self._positions:
            return reject("position_already_open")
        if order.execution_style == "maker":
            # Same discipline as BacktestBroker: no validated model for
            # inferring a resting-order fill from a point-in-time quote.
            return reject("maker_unfilled_no_validated_model")
        if order.limit_price_cents is None:
            # Always a limit order, never a quick/market buy (operator
            # decision): a caller must state the worst price it will accept.
            # This paper broker still fills IMMEDIATELY if the current quote
            # is at or better than that limit (a marketable limit order, not
            # a resting one) -- it just never pays worse than intended, and
            # never fills at "whatever the broker feels like" the way an
            # unconstrained taker order would.
            return reject("limit_price_required")

        if order.side == "yes":
            price_cents = snapshot.yes_ask_cents
        else:
            price_cents = None if snapshot.yes_bid_cents is None else 100 - snapshot.yes_bid_cents

        if price_cents is None or not 1 <= price_cents <= 99:
            return reject("no_fillable_quote")
        if price_cents > order.limit_price_cents:
            return reject("limit_exceeded")

        quantity = order.quantity
        stake = (price_cents / 100) * quantity
        fee = entry_fee_dollars(price_cents, quantity, coefficient=TAKER_FEE_COEFFICIENT)
        cost = stake + fee
        if cost > self._cash:
            return reject("insufficient_funds")

        self._cash -= cost
        filled_at = snapshot.ts or int(time.time())
        row = SimulatedTrade(
            mode="paper",
            market_ticker=order.market_ticker,
            side=order.side,
            quantity=quantity,
            entry_price_cents=price_cents,
            entry_ts=filled_at,
            status="open",
            entry_fee_usd=fee,
        )
        self._session.add(row)
        self._session.flush()  # assign row.id before it's referenced elsewhere this tick
        self._positions[order.market_ticker] = row

        return OrderResult(
            order_id=order_id,
            market_ticker=order.market_ticker,
            side=order.side,
            status="filled",
            quantity=quantity,
            fill_price_cents=price_cents,
            filled_at_ts=filled_at,
        )

    async def cancel_order(self, order_id: str) -> None:
        return None  # fills are immediate against the last-polled quote; nothing rests

    async def get_market_snapshot(self, instrument_id: str) -> MarketSnapshot:
        snapshot = self._quotes.get(instrument_id)
        if snapshot is None:
            return MarketSnapshot(
                market_ticker=instrument_id, ts=0, yes_bid_cents=None, yes_ask_cents=None
            )
        return snapshot
