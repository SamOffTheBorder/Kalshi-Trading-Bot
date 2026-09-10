"""Read-only Coinbase candle adapter for secondary source comparison."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from kalshi_bot.data.external_sources import ACTIVE_CRYPTO_ASSETS
from kalshi_bot.data.normalization import causal_available_at

BASE_URL = "https://api.exchange.coinbase.com"


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
    "CoinbaseCandle",
    "CoinbaseDataError",
    "CoinbasePublicClient",
    "coinbase_product",
    "missing_buckets",
    "parse_candles",
]
