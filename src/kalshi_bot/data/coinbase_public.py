"""Read-only Coinbase candle and trade adapter.

Candles serve the existing secondary-source comparison role. Trades serve
the `constituent` role for BRTI reconstruction (brti-constituent-history):
USD-quoted, at whatever depth Coinbase's public API exposes -- it is not a
deep archive like Kraken's CSV export, so callers should not assume years
of history are reachable here.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx

from kalshi_bot.data.external_sources import ACTIVE_CRYPTO_ASSETS
from kalshi_bot.data.normalization import causal_available_at

BASE_URL = "https://api.exchange.coinbase.com"

# Coinbase Exchange's public /trades endpoint returns at most 1000 rows per
# page and only recent history (it is not a deep archive like Kraken's CSV
# export). This ceiling bounds a single request; acquiring more history
# means paginating with the `after` cursor, bounded by MAX_TRADE_PAGES.
MAX_TRADES_PER_PAGE = 1000
MAX_TRADE_PAGES = 50


class CoinbaseDataError(ValueError):
    """Raised when Coinbase data cannot be safely normalized."""


@dataclass(frozen=True)
class CoinbaseCandle:
    asset_id: str
    product_id: str
    period_seconds: int
    open_ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    observed_at: int
    available_at: int
    retrieved_at: int
    source: str = "coinbase"


@dataclass(frozen=True)
class CoinbaseTrade:
    asset_id: str
    product_id: str
    trade_id: str
    price: float
    quantity: float
    observed_at: int
    available_at: int
    retrieved_at: int
    source: str = "coinbase"


def coinbase_product(asset_id: str) -> str:
    asset = asset_id.upper()
    if asset not in ACTIVE_CRYPTO_ASSETS:
        raise CoinbaseDataError(f"asset is outside the active crypto universe: {asset_id!r}")
    return f"{asset}-USD"


def parse_candles(
    payload: Any,
    *,
    asset_id: str,
    period_seconds: int,
    retrieved_at: int,
) -> tuple[CoinbaseCandle, ...]:
    """Parse Coinbase's [time, low, high, open, close, volume] rows."""

    if period_seconds <= 0 or retrieved_at < 0:
        raise CoinbaseDataError("period_seconds must be positive and retrieved_at non-negative")
    product_id = coinbase_product(asset_id)
    if not isinstance(payload, list):
        raise CoinbaseDataError("Coinbase candle response must be a list")
    rows: list[CoinbaseCandle] = []
    seen: set[int] = set()
    for index, raw in enumerate(payload, start=1):
        if not isinstance(raw, (list, tuple)) or len(raw) < 5:
            raise CoinbaseDataError(f"Coinbase candle row {index} is malformed")
        try:
            open_ts = int(raw[0])
            low, high, open_price, close = (float(raw[i]) for i in (1, 2, 3, 4))
            volume = float(raw[5]) if len(raw) > 5 else 0.0
        except (TypeError, ValueError) as exc:
            raise CoinbaseDataError(f"Coinbase candle row {index} is not numeric") from exc
        if open_ts < 0 or open_ts in seen or high < low or low < 0 or volume < 0:
            raise CoinbaseDataError(f"Coinbase candle row {index} has invalid values")
        seen.add(open_ts)
        observed_at = open_ts + period_seconds
        rows.append(
            CoinbaseCandle(
                asset_id=asset_id.upper(),
                product_id=product_id,
                period_seconds=period_seconds,
                open_ts=open_ts,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
                observed_at=observed_at,
                available_at=causal_available_at(
                    observed_at_ms=observed_at * 1_000,
                    retrieved_at_ms=retrieved_at * 1_000,
                ) // 1_000,
                retrieved_at=retrieved_at,
            )
        )
    return tuple(sorted(rows, key=lambda row: row.open_ts))


def parse_trades(
    payload: Any,
    *,
    asset_id: str,
    retrieved_at: int,
) -> tuple[CoinbaseTrade, ...]:
    """Parse Coinbase's ``{trade_id, price, size, time, ...}`` trade rows."""

    if retrieved_at < 0:
        raise CoinbaseDataError("retrieved_at must be non-negative")
    product_id = coinbase_product(asset_id)
    if not isinstance(payload, list):
        raise CoinbaseDataError("Coinbase trade response must be a list")
    rows: list[CoinbaseTrade] = []
    for index, raw in enumerate(payload, start=1):
        if not isinstance(raw, dict):
            raise CoinbaseDataError(f"Coinbase trade row {index} is malformed")
        try:
            trade_id = str(raw["trade_id"])
            price = float(raw["price"])
            size = float(raw["size"])
            time_str = str(raw["time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CoinbaseDataError(f"Coinbase trade row {index} is missing a field") from exc
        if price <= 0 or size <= 0:
            raise CoinbaseDataError(f"Coinbase trade row {index} has non-positive price/size")
        observed_at_ms = _parse_rfc3339_ms(time_str, row_index=index)
        rows.append(
            CoinbaseTrade(
                asset_id=asset_id.upper(),
                product_id=product_id,
                trade_id=trade_id,
                price=price,
                quantity=size,
                observed_at=observed_at_ms,
                available_at=causal_available_at(
                    observed_at_ms=observed_at_ms, retrieved_at_ms=retrieved_at * 1_000
                ),
                retrieved_at=retrieved_at,
            )
        )
    return tuple(sorted(rows, key=lambda row: row.observed_at))


def _parse_rfc3339_ms(value: str, *, row_index: int) -> int:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise CoinbaseDataError(
            f"Coinbase trade row {row_index} has an invalid timestamp"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return int(parsed.timestamp() * 1_000)


class CoinbasePublicClient:
    """Bounded public candle client; it has no authenticated methods."""

    def __init__(self, *, timeout_s: float = 30.0, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=timeout_s, follow_redirects=True)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> CoinbasePublicClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_candles(
        self,
        *,
        product_id: str,
        start_ts: int,
        end_ts: int,
        granularity_seconds: int,
    ) -> Any:
        if not product_id or start_ts < 0 or end_ts <= start_ts:
            raise CoinbaseDataError("invalid Coinbase candle range")
        if granularity_seconds <= 0:
            raise CoinbaseDataError("granularity_seconds must be positive")
        if (end_ts - start_ts + granularity_seconds - 1) // granularity_seconds > 300:
            raise CoinbaseDataError("Coinbase candle request exceeds 300-bucket bound")
        response = self._client.get(
            f"{BASE_URL}/products/{product_id}/candles",
            params={
                "start": start_ts,
                "end": end_ts,
                "granularity": granularity_seconds,
            },
        )
        response.raise_for_status()
        return response.json()

    def fetch_trades_page(
        self, *, product_id: str, after: str | None = None
    ) -> tuple[Any, str | None]:
        """Fetch one page of recent trades; return (rows, next `after` cursor).

        Bounded to Coinbase's documented page size. The `cb-after` response
        header is the pagination cursor for older trades; its absence means
        there is nothing older left to fetch.
        """

        if not product_id:
            raise CoinbaseDataError("product_id is required")
        params: dict[str, object] = {"limit": MAX_TRADES_PER_PAGE}
        if after is not None:
            params["after"] = after
        response = self._client.get(
            f"{BASE_URL}/products/{product_id}/trades", params=params
        )
        if response.status_code == 429:
            raise CoinbaseDataError("Coinbase rate limit exceeded fetching trades")
        response.raise_for_status()
        return response.json(), response.headers.get("cb-after")

    def fetch_trade_pages(
        self,
        *,
        product_id: str,
        max_pages: int = MAX_TRADE_PAGES,
        sleep_fn=time.sleep,
        rate_limit_delay_s: float = 0.2,
    ) -> Iterator[Any]:
        """Yield successive trade pages, oldest available first.

        Bounded by `max_pages` -- there is no unbounded backfill loop.
        A small delay between requests respects Coinbase's public rate
        limit rather than reacting to a 429 after the fact.
        """

        if max_pages <= 0:
            raise CoinbaseDataError("max_pages must be positive")
        after: str | None = None
        for page in range(max_pages):
            rows, after = self.fetch_trades_page(product_id=product_id, after=after)
            yield rows
            if after is None:
                return
            if page + 1 < max_pages:
                sleep_fn(rate_limit_delay_s)


def missing_buckets(
    candles: tuple[CoinbaseCandle, ...], *, start_ts: int, end_ts: int
) -> tuple[int, ...]:
    """Return absent expected bucket opens; never fill them."""

    if not candles:
        return tuple()
    step = candles[0].period_seconds
    existing = {row.open_ts for row in candles}
    return tuple(ts for ts in range(start_ts, end_ts, step) if ts not in existing)


__all__ = [
    "BASE_URL",
    "MAX_TRADES_PER_PAGE",
    "MAX_TRADE_PAGES",
    "CoinbaseCandle",
    "CoinbaseDataError",
    "CoinbasePublicClient",
    "CoinbaseTrade",
    "coinbase_product",
    "missing_buckets",
    "parse_candles",
    "parse_trades",
]
