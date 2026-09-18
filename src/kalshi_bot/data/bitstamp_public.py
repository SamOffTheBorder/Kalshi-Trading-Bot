"""Read-only Bitstamp trade adapter.

Bitstamp is registered as a BRTI constituent platform
(``external_sources.bitstamp_constituent_instrument``) but had no acquisition
adapter (brti-constituent-history tasks.md 2.4). This module implements one,
mirroring ``coinbase_public.py``'s shape: bounded pagination, causal
``observed_at``/``available_at``, and no forward-filling of missing trades.

Bitstamp's public ``/transactions/{pair}/`` endpoint only exposes a rolling
window (``time=minute|hour|day``), newest-first, with no pagination cursor --
unlike Coinbase's ``cb-after`` header. So there is no "backfill years of
history" path here; this adapter reaches whatever the live rolling window
covers, same as Coinbase's non-deep-archive role for this project.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx

from kalshi_bot.data.external_sources import ACTIVE_CRYPTO_ASSETS
from kalshi_bot.data.normalization import causal_available_at

BASE_URL = "https://www.bitstamp.net/api/v2"

TransactionWindow = Literal["minute", "hour", "day"]


class BitstampDataError(ValueError):
    """Raised when Bitstamp data cannot be safely normalized."""


@dataclass(frozen=True)
class BitstampTrade:
    asset_id: str
    currency_pair: str
    trade_id: str
    price: float
    quantity: float
    observed_at: int
    available_at: int
    retrieved_at: int
    source: str = "bitstamp"


def bitstamp_currency_pair(asset_id: str) -> str:
    asset = asset_id.upper()
    if asset not in ACTIVE_CRYPTO_ASSETS:
        raise BitstampDataError(f"asset is outside the active crypto universe: {asset_id!r}")
    return f"{asset.lower()}usd"


def parse_trades(
    payload: Any,
    *,
    asset_id: str,
    retrieved_at: int,
) -> tuple[BitstampTrade, ...]:
    """Parse Bitstamp's ``{tid, price, amount, date, ...}`` trade rows.

    ``date`` is a decimal-string Unix timestamp in whole seconds.
    """

    if retrieved_at < 0:
        raise BitstampDataError("retrieved_at must be non-negative")
    currency_pair = bitstamp_currency_pair(asset_id)
    if not isinstance(payload, list):
        raise BitstampDataError("Bitstamp trade response must be a list")
    rows: list[BitstampTrade] = []
    for index, raw in enumerate(payload, start=1):
        if not isinstance(raw, dict):
            raise BitstampDataError(f"Bitstamp trade row {index} is malformed")
        try:
            trade_id = str(raw["tid"])
            price = float(raw["price"])
            amount = float(raw["amount"])
            date_raw = str(raw["date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BitstampDataError(f"Bitstamp trade row {index} is missing a field") from exc
        if price <= 0 or amount <= 0:
            raise BitstampDataError(f"Bitstamp trade row {index} has non-positive price/amount")
        try:
            observed_at_s = int(date_raw)
        except ValueError as exc:
            raise BitstampDataError(
                f"Bitstamp trade row {index} has an invalid timestamp"
            ) from exc
        if observed_at_s < 0:
            raise BitstampDataError(f"Bitstamp trade row {index} has a negative timestamp")
        observed_at_ms = observed_at_s * 1_000
        rows.append(
            BitstampTrade(
                asset_id=asset_id.upper(),
                currency_pair=currency_pair,
                trade_id=trade_id,
                price=price,
                quantity=amount,
                observed_at=observed_at_ms,
                available_at=causal_available_at(
                    observed_at_ms=observed_at_ms, retrieved_at_ms=retrieved_at * 1_000
                ),
                retrieved_at=retrieved_at,
            )
        )
    return tuple(sorted(rows, key=lambda row: row.observed_at))


class BitstampPublicClient:
    """Bounded public trade client; it has no authenticated methods."""

    def __init__(self, *, timeout_s: float = 30.0, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=timeout_s, follow_redirects=True)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> BitstampPublicClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_transactions(
        self, *, currency_pair: str, window: TransactionWindow = "hour"
    ) -> Any:
        """Fetch Bitstamp's rolling transaction window for one pair.

        There is no pagination cursor on this endpoint -- ``window`` bounds
        how far back the returned rows can reach (Bitstamp documents
        "minute", "hour", or "day"). Reaching further history than "day"
        covers is not possible through this endpoint.
        """

        if not currency_pair:
            raise BitstampDataError("currency_pair is required")
        response = self._client.get(
            f"{BASE_URL}/transactions/{currency_pair}/", params={"time": window}
        )
        if response.status_code == 429:
            raise BitstampDataError("Bitstamp rate limit exceeded fetching transactions")
        response.raise_for_status()
        return response.json()


def missing_seconds(
    trades: tuple[BitstampTrade, ...], *, start_ts: int, end_ts: int
) -> tuple[int, ...]:
    """Return whole seconds in ``[start_ts, end_ts)`` with no trade; never fill them."""

    existing = {row.observed_at // 1_000 for row in trades}
    return tuple(ts for ts in range(start_ts, end_ts) if ts not in existing)


__all__ = [
    "BASE_URL",
    "BitstampDataError",
    "BitstampPublicClient",
    "BitstampTrade",
    "TransactionWindow",
    "bitstamp_currency_pair",
    "missing_seconds",
    "parse_trades",
]
