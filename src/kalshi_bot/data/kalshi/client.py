"""Unauthenticated Kalshi client for public market data.

Backtesting must work with zero credentials (spec: kalshi-market-data), so
this client covers only public endpoints: markets, events, series, and
historical candlesticks. Order placement lives elsewhere, in a later change.

Rate limiting is client-side at or below Kalshi's Basic tier (20 reads/sec),
with exponential backoff on 429/5xx and fail-fast on 401/403.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

import httpx
from loguru import logger

PROD_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Candlestick endpoint rejects ranges longer than 5000 periods per request.
MAX_PERIODS_PER_REQUEST = 5000

VALID_PERIOD_MINUTES = (1, 60, 1440)


class KalshiAuthError(Exception):
    """401/403 from the API — never retried."""


class _RateLimiter:
    """Sliding-window limiter: at most `max_calls` per `window_s` seconds."""

    def __init__(self, max_calls: int, window_s: float = 1.0) -> None:
        self.max_calls = max_calls
        self.window_s = window_s
        self._calls: deque[float] = deque()

    def acquire(self) -> None:
        now = time.monotonic()
        while self._calls and now - self._calls[0] > self.window_s:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            sleep_for = self.window_s - (now - self._calls[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
        self._calls.append(time.monotonic())


class KalshiPublicClient:
    def __init__(
        self,
        base_url: str = PROD_BASE_URL,
        *,
        max_reads_per_second: int = 8,  # unauthenticated throttling observed well below 20/s
        max_retries: int = 4,
        timeout_s: float = 15.0,
    ) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout_s)
        self._limiter = _RateLimiter(max_reads_per_second)
        self._max_retries = max_retries

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> KalshiPublicClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transport -----------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        backoff = 1.0
        for attempt in range(1, self._max_retries + 1):
            self._limiter.acquire()
            response = self._client.get(path, params=params)
            if response.status_code in (401, 403):
                raise KalshiAuthError(f"{response.status_code} on {path}: {response.text[:200]}")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self._max_retries:
                    response.raise_for_status()
                logger.warning(
                    "Kalshi {} on {} (attempt {}/{}), backing off {:.1f}s",
                    response.status_code,
                    path,
                    attempt,
                    self._max_retries,
                    backoff,
                )
                time.sleep(backoff)
                backoff *= 2
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError("unreachable")  # pragma: no cover

    # -- public endpoints ------------------------------------------------------

    def get_series(self, series_ticker: str) -> dict[str, Any]:
        return self._get(f"/series/{series_ticker}")["series"]

    def get_markets(
        self,
        *,
        series_ticker: str | None = None,
        event_ticker: str | None = None,
        status: str | None = None,
        min_close_ts: int | None = None,
        max_close_ts: int | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """One page of markets. Returns (markets, next_cursor)."""
        params: dict[str, Any] = {"limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        if status:
            params["status"] = status
        if min_close_ts is not None:
            params["min_close_ts"] = min_close_ts
        if max_close_ts is not None:
            params["max_close_ts"] = max_close_ts
        if cursor:
            params["cursor"] = cursor
        data = self._get("/markets", params)
        return data.get("markets", []), data.get("cursor") or None

    def iter_markets(self, **kwargs: Any):
        """Iterate all markets across pagination."""
        cursor: str | None = None
        while True:
            markets, cursor = self.get_markets(cursor=cursor, **kwargs)
            yield from markets
            if not cursor:
                return

    def get_candlesticks(
        self,
        series_ticker: str,
        market_ticker: str,
        *,
        start_ts: int,
        end_ts: int,
        period_minutes: int,
    ) -> list[dict[str, Any]]:
        """All candlesticks for a market in [start_ts, end_ts], auto-chunked
        to respect the 5000-period-per-request API limit."""
        if period_minutes not in VALID_PERIOD_MINUTES:
            raise ValueError(f"period_minutes must be one of {VALID_PERIOD_MINUTES}")
        period_s = period_minutes * 60
        chunk_s = MAX_PERIODS_PER_REQUEST * period_s
        out: list[dict[str, Any]] = []
        chunk_start = start_ts
        while chunk_start <= end_ts:
            chunk_end = min(chunk_start + chunk_s - period_s, end_ts)
            data = self._get(
                f"/series/{series_ticker}/markets/{market_ticker}/candlesticks",
                {
                    "start_ts": chunk_start,
                    "end_ts": chunk_end,
                    "period_interval": period_minutes,
                },
            )
            out.extend(data.get("candlesticks", []))
            chunk_start = chunk_end + period_s
        return out
