"""The BrokerAdapter protocol — the seam that makes backtest/paper/live
interchangeable.

Introduced now, with BacktestBroker as the first implementation, so the
strategy/risk layers are written against the abstraction from day one.
KalshiBroker (live) and PaperBroker arrive in later changes and implement
this same protocol.

Money convention matches the rest of the codebase: contract prices are
integer cents, account balances are float USD.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

Side = Literal["yes", "no"]


ExecutionStyle = Literal["taker", "maker"]


class OrderRequest(BaseModel):
    market_ticker: str
    side: Side
    quantity: int = Field(gt=0)
    # None = take the market (fill at the adapter's fill model);
    # set = reject if the marketable price is worse than this.
    limit_price_cents: int | None = Field(default=None, ge=1, le=99)
    # "taker" (default) crosses the spread, pays the taker fee (~4x maker).
    # "maker" rests at `limit_price_cents` (required) and fills only if the
    # market traded through that level — pays the maker fee. Design decision
    # D-fees (design.md): "design for maker fills wherever the strategy's
    # latency budget allows" — maker vs taker is worth ~4x on fees.
    execution_style: ExecutionStyle = "taker"


class OrderResult(BaseModel):
    order_id: str
    market_ticker: str
    side: Side
    status: Literal["filled", "rejected"]
    quantity: int = 0
    fill_price_cents: int | None = None
    filled_at_ts: int | None = None
    reject_reason: str | None = None


class Position(BaseModel):
    market_ticker: str
    side: Side
    quantity: int
    avg_entry_price_cents: float


class MarketSnapshot(BaseModel):
    market_ticker: str
    ts: int
    yes_bid_cents: int | None
    yes_ask_cents: int | None


@runtime_checkable
class BrokerAdapter(Protocol):
    @property
    def broker_name(self) -> str: ...

    async def get_account_balance(self) -> float: ...

    async def get_open_positions(self) -> list[Position]: ...

    async def place_order(self, order: OrderRequest) -> OrderResult: ...

    async def cancel_order(self, order_id: str) -> None: ...

    async def get_market_snapshot(self, instrument_id: str) -> MarketSnapshot: ...
