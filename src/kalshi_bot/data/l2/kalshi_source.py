"""L2 source: Kalshi's public, unauthenticated ``/markets/{ticker}/orderbook``.

Unlike perp marks (one list call covers every ticker), Kalshi's order book is
a per-market endpoint -- one request per ticker per tick. And unlike BRTI or
perps (a fixed set of tickers for the whole run), KXBTC15M's tradable
markets roll over every 15 minutes, so the set of tickers to poll must be
rediscovered periodically rather than fixed at start.

``KalshiL2Source`` re-lists the series' currently ``open`` markets every
``rediscover_every_s`` (default 5 minutes -- frequent enough that a new
15-minute window is picked up promptly, infrequent enough not to spend a
full ``/markets`` list call every tick) and polls the order book for each.

Read-only. No ``/orders`` path is touched, and no API key is required.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from loguru import logger

from kalshi_bot.data.l2.poll import L2ReadingRaw

DEFAULT_REDISCOVER_EVERY_S = 300.0


class _MarketsAndOrderbookClient(Protocol):
    """The two read-only methods `KalshiL2Source` needs -- `KalshiPublicClient`
    satisfies this structurally, and a test fake can too without importing
    the real client."""

    def get_markets(
        self, *, series_ticker: str | None = ..., status: str | None = ...
    ) -> tuple[list[dict[str, Any]], str | None]: ...

    def get_orderbook(self, market_ticker: str, *, depth: int | None = ...) -> dict[str, Any]: ...


def parse_orderbook(body: object) -> tuple[list[list[str]], list[list[str]]] | None:
    """Extract ``(bids, asks)`` price/size pairs from Kalshi's orderbook
    response. Returns ``None`` when the shape is not usable -- a skipped
    ticker for this tick, not an error."""
    if not isinstance(body, dict):
        return None
    node = body.get("orderbook_fp")
    if not isinstance(node, dict):
        return None
    bids = node.get("no_dollars")
    asks = node.get("yes_dollars")
    if not isinstance(bids, list) or not isinstance(asks, list):
        return None
    return bids, asks


class KalshiL2Source:
    """``L2Source`` backed by Kalshi's public orderbook endpoint, rediscovering
    the series' open markets on a timer rather than a fixed ticker list.

    ``fetch()`` returns one reading per currently open ticker, or an empty
    list on a transient failure (timeout, 5xx) for that ticker only -- one
    market's hiccup does not drop the others.
    """

    name = "kalshi:orderbook"

    def __init__(
        self,
        client: _MarketsAndOrderbookClient,
        *,
        series_ticker: str,
        depth: int | None = None,
        rediscover_every_s: float = DEFAULT_REDISCOVER_EVERY_S,
        now_fn: Callable[[], float] = time.time,
        name: str = "kalshi:orderbook",
    ) -> None:
        if not series_ticker:
            raise ValueError("series_ticker is required")
        self._client = client
        self._series_ticker = series_ticker
        self._depth = depth
        self._rediscover_every_s = rediscover_every_s
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
                "l2 market discovery for {} failed, keeping {} previous ticker(s): {}",
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
                "l2 source {} now polling {} open market(s): {}",
                self._series_ticker,
                len(tickers),
                ", ".join(tickers) or "(none)",
            )
        self._tickers = tickers

    def fetch(self) -> list[L2ReadingRaw]:
        now = self._now_fn()
        if now >= self._next_rediscover_at:
            self._rediscover()
            self._next_rediscover_at = now + self._rediscover_every_s

        out: list[L2ReadingRaw] = []
        for ticker in self._tickers:
            try:
                body = self._client.get_orderbook(ticker, depth=self._depth)
            except Exception as exc:  # one market's timeout must not stop the rest
                logger.warning("orderbook fetch failed for {}: {}", ticker, exc)
                continue
            parsed = parse_orderbook(body)
            if parsed is None:
                continue
            bids, asks = parsed
            out.append(L2ReadingRaw(market_ticker=ticker, bids=bids, asks=asks))
        return out


__all__ = [
    "DEFAULT_REDISCOVER_EVERY_S",
    "KalshiL2Source",
    "parse_orderbook",
]
