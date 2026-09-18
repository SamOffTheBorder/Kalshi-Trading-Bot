"""Restart-safe order state for paper and perp execution.

The tracker intentionally owns only client-order-id state.  Broker adapters
remain responsible for API calls; startup reconciliation supplies the broker's
authoritative order/fill snapshot to :meth:`reconcile`.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class TrackedOrder:
    client_order_id: str
    broker_order_id: str | None
    market_ticker: str
    requested_quantity: float
    filled_quantity: float = 0.0
    status: str = "pending"
    created_at_ts: int = 0
    updated_at_ts: int = 0
    last_fill_price: float | None = None
    cancel_reason: str | None = None

    @property
    def remaining_quantity(self) -> float:
        return max(0.0, self.requested_quantity - self.filled_quantity)


class OrderTracker:
    """Persistent idempotency registry and restart reconciliation ledger."""

    def __init__(self, path: str | Path, *, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self._clock = clock
        self.orders: dict[str, TrackedOrder] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.orders = {
            key: TrackedOrder(**value) for key, value in payload.get("orders", {}).items()
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f"{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"orders": {k: asdict(v) for k, v in self.orders.items()}}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def register(
        self, client_order_id: str, *, market_ticker: str, requested_quantity: float,
        broker_order_id: str | None = None,
    ) -> TrackedOrder:
        """Return the existing record for a retry; never duplicate an ID."""
        if requested_quantity <= 0:
            raise ValueError("requested_quantity must be positive")
        existing = self.orders.get(client_order_id)
        if existing is not None:
            if (
                existing.market_ticker != market_ticker
                or existing.requested_quantity != requested_quantity
            ):
                raise ValueError(
                    "client_order_id is already registered with different order details"
                )
            return existing
        now = int(self._clock())
        order = TrackedOrder(client_order_id, broker_order_id, market_ticker, requested_quantity,
                             created_at_ts=now, updated_at_ts=now)
        self.orders[client_order_id] = order
        self.save()
        return order

    def record_fill(
        self, client_order_id: str, quantity: float, *, price: float | None = None
    ) -> TrackedOrder:
        if quantity <= 0:
            raise ValueError("fill quantity must be positive")
        order = self._get(client_order_id)
        order.filled_quantity = min(order.requested_quantity, order.filled_quantity + quantity)
        order.last_fill_price = price
        order.status = "filled" if order.remaining_quantity == 0 else "partial"
        order.updated_at_ts = int(self._clock())
        self.save()
        return order

    def mark_cancelled(self, client_order_id: str, *, reason: str = "cancelled") -> TrackedOrder:
        order = self._get(client_order_id)
        if order.remaining_quantity > 0:
            order.status = "cancelled"
            order.cancel_reason = reason
            order.updated_at_ts = int(self._clock())
            self.save()
        return order

    def stale_orders(
        self, *, now_ts: int | None = None, max_age_seconds: int
    ) -> list[TrackedOrder]:
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds must be non-negative")
        now = int(self._clock()) if now_ts is None else now_ts
        return [
            order for order in self.orders.values()
            if order.status in {"pending", "partial"}
            and now - order.created_at_ts >= max_age_seconds
            and order.remaining_quantity > 0
        ]

    def cancel_stale(
        self,
        cancel: Callable[[TrackedOrder], None],
        *,
        now_ts: int | None = None,
        max_age_seconds: int,
    ) -> list[TrackedOrder]:
        """Cancel each stale broker order, recording only successful calls."""
        stale = self.stale_orders(now_ts=now_ts, max_age_seconds=max_age_seconds)
        for order in stale:
            cancel(order)
            self.mark_cancelled(order.client_order_id, reason="stale_order")
        return stale

    def reconcile(
        self, broker_orders: Iterable[dict[str, Any]], *, now_ts: int | None = None
    ) -> list[TrackedOrder]:
        """Merge broker truth after restart and return orders needing action.

        Broker payloads may use either ``client_order_id``/``order_id`` and
        ``filled_quantity``/``filled_count``. Missing local orders are adopted
        so fills that landed while the process was down are never lost.
        """
        for raw in broker_orders:
            client_id = raw.get("client_order_id")
            if not client_id:
                continue
            requested = float(raw.get("requested_quantity", raw.get("count", 0)))
            if requested <= 0:
                continue
            order = self.orders.get(client_id) or self.register(
                client_id,
                market_ticker=str(raw.get("market_ticker", raw.get("ticker", "unknown"))),
                requested_quantity=requested,
                broker_order_id=raw.get("order_id"),
            )
            filled = float(
                raw.get("filled_quantity", raw.get("filled_count", order.filled_quantity))
            )
            order.filled_quantity = min(
                order.requested_quantity, max(order.filled_quantity, filled)
            )
            remote_status = str(raw.get("status", order.status)).lower()
            if order.remaining_quantity == 0:
                order.status = "filled"
            elif remote_status in {"cancelled", "canceled", "closed", "rejected"}:
                order.status = "cancelled" if remote_status != "rejected" else "rejected"
            elif order.filled_quantity > 0:
                order.status = "partial"
            order.updated_at_ts = int(self._clock() if now_ts is None else now_ts)
        self.save()
        return self.stale_orders(now_ts=now_ts, max_age_seconds=0)

    def _get(self, client_order_id: str) -> TrackedOrder:
        try:
            return self.orders[client_order_id]
        except KeyError as exc:
            raise KeyError(f"unknown client_order_id: {client_order_id}") from exc


__all__ = ["OrderTracker", "TrackedOrder"]
