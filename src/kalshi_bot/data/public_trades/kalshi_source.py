"""Public-trade source: Kalshi's public, unauthenticated ``/markets/trades``.

Like L2, KXBTC15M's tradable markets roll over every 15 minutes, so the
tickers to poll are rediscovered periodically (see ``l2.kalshi_source`` for
the same reasoning) rather than fixed at start.

``GET /markets/trades`` supports ``ticker`` + ``min_ts`` filtering and
cursor pagination, so each tick asks for exactly the trades that landed
since the last-seen ``observed_at`` per ticker and follows the cursor until
a page comes back short of the limit (caught up) -- bounded by
``max_pages_per_ticker`` so one very active market cannot stall the whole
tick.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from typing import Any, Protocol

from loguru import logger

from kalshi_bot.data.public_trades.poll import TradeReadingRaw

DEFAULT_REDISCOVER_EVERY_S = 300.0
DEFAULT_MAX_PAGES_PER_TICKER = 20


class _MarketsAndTradesClient(Protocol):
    """The two read-only methods `KalshiTradeSource` needs -- `KalshiPublicClient`
    satisfies this structurally, and a test fake can too without importing
    the real client."""

    def get_markets(
        self, *, series_ticker: str | None = ..., status: str | None = ...
    ) -> tuple[list[dict[str, Any]], str | None]: ...

    def get_trades(
        self,
        *,
        ticker: str | None = ...,
        min_ts: int | None = ...,
        max_ts: int | None = ...,
        limit: int = ...,
        cursor: str | None = ...,
    ) -> tuple[list[dict[str, Any]], str | None]: ...


def _parse_created_time(value: object) -> int | None:
    """Kalshi's ``created_time`` is RFC3339 UTC with fractional seconds."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return int(parsed.timestamp())


def parse_trade(entry: object) -> TradeReadingRaw | None:
    """Turn one ``/markets/trades`` entry into a ``TradeReadingRaw``.

    Returns ``None`` (a skipped row, not an error) when the entry lacks a
    usable ticker, trade id, timestamp, or YES price.
    """
    if not isinstance(entry, dict):
        return None
    ticker = entry.get("ticker")
    trade_id = entry.get("trade_id")
    if not isinstance(ticker, str) or not ticker:
        return None
    if not isinstance(trade_id, str) or not trade_id:
        return None
    observed_at = _parse_created_time(entry.get("created_time"))
    price = entry.get("yes_price_dollars")
    quantity = entry.get("count_fp")
    if observed_at is None or not isinstance(price, str) or not isinstance(quantity, str):
        return None
    taker_side = entry.get("taker_side")
    return TradeReadingRaw(
        market_ticker=ticker,
        trade_id=trade_id,
        observed_at=observed_at,
        price_dollars=price,
        quantity_fp=quantity,
        taker_side=taker_side if isinstance(taker_side, str) else None,
        available_at=None,  # poll loop stamps local receipt time
        extra={
            "taker_book_side": entry.get("taker_book_side"),
            "taker_outcome_side": entry.get("taker_outcome_side"),
            "is_block_trade": entry.get("is_block_trade"),
        },
    )


class KalshiTradeSource:
    """``TradeSource`` backed by Kalshi's public ``/markets/trades`` endpoint,
    rediscovering the series' open markets on a timer.

    ``fetch(since_by_ticker)`` pages each open ticker forward from its
    last-seen ``observed_at`` (or pulls the most recent page only, for a
    ticker with no prior state -- it does not backfill a newly discovered
    market's entire history) until a page comes back short of the request
    limit or ``max_pages_per_ticker`` is hit. One ticker's failure does not
    stop the others.
    """

    name = "kalshi:trades"

    def __init__(
        self,
        client: _MarketsAndTradesClient,
        *,
        series_ticker: str,
        rediscover_every_s: float = DEFAULT_REDISCOVER_EVERY_S,
        max_pages_per_ticker: int = DEFAULT_MAX_PAGES_PER_TICKER,
        page_limit: int = 1000,
        now_fn: Callable[[], float] = time.time,
        name: str = "kalshi:trades",
    ) -> None:
        if not series_ticker:
            raise ValueError("series_ticker is required")
        if max_pages_per_ticker <= 0:
            raise ValueError("max_pages_per_ticker must be positive")
        self._client = client
        self._series_ticker = series_ticker
        self._rediscover_every_s = rediscover_every_s
        self._max_pages_per_ticker = max_pages_per_ticker
        self._page_limit = page_limit
        self._now_fn = now_fn
        self.name = name
        self._tickers: list[str] = []
        self._next_rediscover_at = 0.0

    def _rediscover(self) -> None:
        try:
            markets, _cursor = self._client.get_markets(
                series_ticker=self._series_ticker, status="open"
            )
        except Exception as exc:  # transient -> keep the previous ticker list
            logger.warning(
                "trade market discovery for {} failed, keeping {} previous ticker(s): {}",
                self._series_ticker,
                len(self._tickers),
                exc,
            )
            return
        tickers = sorted(
            m["ticker"] for m in markets if isinstance(m, dict) and m.get("ticker")
        )
        if tickers != self._tickers:
            logger.info(
                "trade source {} now polling {} open market(s): {}",
                self._series_ticker,
                len(tickers),
                ", ".join(tickers) or "(none)",
            )
        self._tickers = tickers

    def _fetch_ticker(self, ticker: str, since: int | None) -> list[TradeReadingRaw]:
        out: list[TradeReadingRaw] = []
        cursor: str | None = None
        # `min_ts` is inclusive server-side; a ticker's own dedup-by-trade-id
        # in the poll loop handles the boundary trade being re-fetched once.
        min_ts = since
        for _page in range(self._max_pages_per_ticker):
            try:
                rows, cursor = self._client.get_trades(
                    ticker=ticker, min_ts=min_ts, limit=self._page_limit, cursor=cursor
                )
            except Exception as exc:  # one ticker's timeout must not stop the rest
                logger.warning("trades fetch failed for {}: {}", ticker, exc)
                break
            for row in rows:
                reading = parse_trade(row)
                if reading is not None:
                    out.append(reading)
            if not cursor or len(rows) < self._page_limit:
                break
        return out

    def fetch(self, since_by_ticker: dict[str, int | None]) -> list[TradeReadingRaw]:
        now = self._now_fn()
        if now >= self._next_rediscover_at:
            self._rediscover()
            self._next_rediscover_at = now + self._rediscover_every_s

        out: list[TradeReadingRaw] = []
        for ticker in self._tickers:
            out.extend(self._fetch_ticker(ticker, since_by_ticker.get(ticker)))
        return out


__all__ = [
    "DEFAULT_MAX_PAGES_PER_TICKER",
    "DEFAULT_REDISCOVER_EVERY_S",
    "KalshiTradeSource",
    "parse_trade",
]
