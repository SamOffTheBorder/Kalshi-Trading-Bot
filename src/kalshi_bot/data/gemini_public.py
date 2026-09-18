"""Read-only Gemini trade adapter.

Gemini is registered as a BRTI constituent platform
(``external_sources.gemini_constituent_instrument``) but had no acquisition
adapter (brti-constituent-history tasks.md 2.4). This module implements one,
mirroring ``coinbase_public.py``'s shape: bounded pagination, causal
``observed_at``/``available_at``, and no forward-filling of missing trades.

Gemini's public ``/v1/trades/:symbol`` endpoint returns up to
``limit_trades`` rows (max 500) per call, newest-first by default, and takes
a ``since_tid`` cursor to page backward through history -- closer to
Coinbase's ``cb-after`` pagination than Bitstamp's fixed rolling window.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx

from kalshi_bot.data.external_sources import ACTIVE_CRYPTO_ASSETS
from kalshi_bot.data.normalization import causal_available_at

BASE_URL = "https://api.gemini.com/v1"

# Gemini documents 500 as the maximum `limit_trades` per request. This bounds
# a single call; deeper history means paginating with `since_tid`, bounded
# by MAX_TRADE_PAGES -- there is no unbounded backfill loop.
MAX_TRADES_PER_PAGE = 500
MAX_TRADE_PAGES = 50


class GeminiDataError(ValueError):
    """Raised when Gemini data cannot be safely normalized."""


@dataclass(frozen=True)
class GeminiTrade:
    asset_id: str
    symbol: str
    trade_id: str
    price: float
    quantity: float
    observed_at: int
    available_at: int
    retrieved_at: int
    source: str = "gemini"


def gemini_symbol(asset_id: str) -> str:
    asset = asset_id.upper()
    if asset not in ACTIVE_CRYPTO_ASSETS:
        raise GeminiDataError(f"asset is outside the active crypto universe: {asset_id!r}")
    return f"{asset.lower()}usd"


def parse_trades(
    payload: Any,
    *,
    asset_id: str,
    retrieved_at: int,
) -> tuple[GeminiTrade, ...]:
    """Parse Gemini's ``{tid, price, amount, timestampms, ...}`` trade rows."""

    if retrieved_at < 0:
        raise GeminiDataError("retrieved_at must be non-negative")
    symbol = gemini_symbol(asset_id)
    if not isinstance(payload, list):
        raise GeminiDataError("Gemini trade response must be a list")
    rows: list[GeminiTrade] = []
    for index, raw in enumerate(payload, start=1):
        if not isinstance(raw, dict):
            raise GeminiDataError(f"Gemini trade row {index} is malformed")
        try:
            trade_id = str(raw["tid"])
            price = float(raw["price"])
            amount = float(raw["amount"])
            observed_at_ms = int(raw["timestampms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GeminiDataError(f"Gemini trade row {index} is missing a field") from exc
        if price <= 0 or amount <= 0:
            raise GeminiDataError(f"Gemini trade row {index} has non-positive price/amount")
        if observed_at_ms < 0:
            raise GeminiDataError(f"Gemini trade row {index} has a negative timestamp")
        rows.append(
            GeminiTrade(
                asset_id=asset_id.upper(),
                symbol=symbol,
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


class GeminiPublicClient:
    """Bounded public trade client; it has no authenticated methods."""

    def __init__(self, *, timeout_s: float = 30.0, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=timeout_s, follow_redirects=True)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> GeminiPublicClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_trades_page(
        self, *, symbol: str, since_tid: int | None = None
    ) -> Any:
        """Fetch one page of trades, oldest-first when ``since_tid`` is given.

        Without ``since_tid``, Gemini returns its most recent
        ``limit_trades`` rows. With it, rows strictly after that trade ID
        are returned -- the documented way to page forward through history
        once a starting point is known.
        """

        if not symbol:
            raise GeminiDataError("symbol is required")
        params: dict[str, object] = {"limit_trades": MAX_TRADES_PER_PAGE}
        if since_tid is not None:
            params["since_tid"] = since_tid
        response = self._client.get(f"{BASE_URL}/trades/{symbol}", params=params)
        if response.status_code == 429:
            raise GeminiDataError("Gemini rate limit exceeded fetching trades")
        response.raise_for_status()
        return response.json()

    def fetch_trade_pages(
        self,
        *,
        symbol: str,
        start_tid: int,
        max_pages: int = MAX_TRADE_PAGES,
        sleep_fn=time.sleep,
        rate_limit_delay_s: float = 0.5,
    ) -> Iterator[Any]:
        """Yield successive trade pages forward from ``start_tid``.

        Bounded by ``max_pages`` -- there is no unbounded backfill loop. A
        small delay between requests respects Gemini's public rate limit
        rather than reacting to a 429 after the fact. Stops early once a
        page returns fewer than a full page (nothing further to fetch).
        """

        if max_pages <= 0:
            raise GeminiDataError("max_pages must be positive")
        since_tid = start_tid
        for page in range(max_pages):
            rows = self.fetch_trades_page(symbol=symbol, since_tid=since_tid)
            if not isinstance(rows, list):
                raise GeminiDataError("Gemini trade page response must be a list")
            yield rows
            if len(rows) < MAX_TRADES_PER_PAGE:
                return
            max_tid = max(int(row["tid"]) for row in rows if isinstance(row, dict) and "tid" in row)
            since_tid = max_tid
            if page + 1 < max_pages:
                sleep_fn(rate_limit_delay_s)


def missing_seconds(
    trades: tuple[GeminiTrade, ...], *, start_ts: int, end_ts: int
) -> tuple[int, ...]:
    """Return whole seconds in ``[start_ts, end_ts)`` with no trade; never fill them."""

    existing = {row.observed_at // 1_000 for row in trades}
    return tuple(ts for ts in range(start_ts, end_ts) if ts not in existing)


__all__ = [
    "BASE_URL",
    "MAX_TRADES_PER_PAGE",
    "MAX_TRADE_PAGES",
    "GeminiDataError",
    "GeminiPublicClient",
    "GeminiTrade",
    "gemini_symbol",
    "missing_seconds",
    "parse_trades",
]
