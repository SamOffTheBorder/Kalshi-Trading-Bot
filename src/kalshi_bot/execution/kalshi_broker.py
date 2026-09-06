"""KalshiBroker: implements BrokerAdapter against the live/demo Kalshi API
(spec: kalshi-authenticated-api, tasks.md §4.3).

`KalshiAuthenticatedClient` is synchronous (plain `httpx.Client`); every
method here offloads the blocking call via `asyncio.to_thread` so this class
satisfies the async `BrokerAdapter` protocol without a second HTTP stack.

**Not smoke-tested against any live environment (demo or prod) as of this
change.** Order placement in particular must not be exercised against a real
account without an explicit, separate go-ahead — see tasks.md 4.3.

Only event-contract (not perps/`/margin`) order placement is covered — that's
task 4.4, not this file.
"""

from __future__ import annotations

import asyncio

from kalshi_bot.execution.broker_protocol import (
    MarketSnapshot,
    OrderRequest,
    OrderResult,
    Position,
)
from kalshi_bot.execution.kalshi_client import KalshiAuthenticatedClient


class KalshiBroker:
    """Implements BrokerAdapter against the real Kalshi event-contract API."""

    def __init__(self, client: KalshiAuthenticatedClient) -> None:
        self._client = client

    @property
    def broker_name(self) -> str:
        return "kalshi"

    async def get_account_balance(self) -> float:
        data = await asyncio.to_thread(self._client.get_balance)
        # API reports balance in integer cents.
        return data["balance"] / 100

    async def get_open_positions(self) -> list[Position]:
        data = await asyncio.to_thread(self._client.get_positions)
        positions: list[Position] = []
        for raw in data.get("market_positions", []):
            quantity = raw.get("position", 0)
            if quantity == 0:
                continue
            side = "yes" if quantity > 0 else "no"
            positions.append(
                Position(
                    market_ticker=raw["ticker"],
                    side=side,
                    quantity=abs(quantity),
                    avg_entry_price_cents=raw.get("market_exposure_dollars", 0.0),
                )
            )
        return positions

    async def place_order(self, order: OrderRequest) -> OrderResult:
        order_type = "market" if order.limit_price_cents is None else "limit"
        yes_price_cents = order.limit_price_cents if order.side == "yes" else None
        no_price_cents = order.limit_price_cents if order.side == "no" else None

        response = await asyncio.to_thread(
            self._client.create_order,
            market_ticker=order.market_ticker,
            side=order.side,
            action="buy",
            count=order.quantity,
            order_type=order_type,
            yes_price_cents=yes_price_cents,
            no_price_cents=no_price_cents,
        )
        raw_order = response.get("order", {})
        status = raw_order.get("status")
        order_id = raw_order.get("order_id", "")
        # "resting" = a limit order still sitting on the book, unfilled (or
        # partially filled) — OrderResult has no "resting" status of its own,
        # so treat any fill_count of 0 as "rejected" from the caller's
        # perspective (nothing to act on yet) rather than falsely claim a fill.
        filled_count = raw_order.get("taker_fill_count", 0)
        if status == "executed" or (status == "resting" and filled_count > 0):
            fill_price = (
                raw_order.get("yes_price") if order.side == "yes" else raw_order.get("no_price")
            )
            return OrderResult(
                order_id=order_id,
                market_ticker=order.market_ticker,
                side=order.side,
                status="filled",
                quantity=filled_count or raw_order.get("count", 0),
                fill_price_cents=fill_price,
            )
        return OrderResult(
            order_id=order_id,
            market_ticker=order.market_ticker,
            side=order.side,
            status="rejected",
            reject_reason=str(status) if status != "resting" else "resting_unfilled",
        )

    async def cancel_order(self, order_id: str) -> None:
        await asyncio.to_thread(self._client.cancel_order, order_id)

    async def get_market_snapshot(self, instrument_id: str) -> MarketSnapshot:
        # No public-market-data call is wired here yet — the authenticated
        # client only exposes account/portfolio endpoints. A real snapshot
        # should come from data/kalshi/client.py's public client instead;
        # this stub exists only to satisfy the protocol until §4.4/§4.6 wire
        # a live market-data source into the broker.
        raise NotImplementedError(
            "KalshiBroker.get_market_snapshot: use data.kalshi.client.KalshiPublicClient "
            "for live market data; not wired here yet."
        )


__all__ = ["KalshiBroker"]
