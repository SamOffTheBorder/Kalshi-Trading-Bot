"""Perp-mark source: Kalshi's authenticated ``/margin/markets`` endpoint.

``GET /trade-api/v2/margin/markets`` returns every margin (perp) market in one
call, each entry carrying ``settlement_mark_price: {price, ts_ms}`` (the mark
this loop records), ``reference_price`` (the underlying index reference),
``liquidation_mark_price``, ``bid`` / ``ask``, ``open_interest``,
``contract_size`` and ``leverage_estimate``. Prices are Kalshi fixed-point
dollar strings **per contract** (a BTC perp contract is 0.0001 BTC).

One list call covers all wanted tickers, so ``fetch()`` returns a snapshot per
ticker on each tick — cheaper and more consistent than one call per market.
Signing, host and key are identical to ``KalshiMarginClient`` (this wraps it).

Read-only. No ``/orders`` path is touched.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from loguru import logger

from kalshi_bot.data.perps.mark_poll import PerpMarkReadingRaw
from kalshi_bot.execution.kalshi_client import KalshiAuthError

SOURCE_LABEL = "kalshi:margin/markets"


class _MarginMarketsClient(Protocol):
    """The one method `KalshiPerpMarkSource` needs from a margin client —
    `KalshiMarginClient` satisfies it structurally, and a test fake can too
    without importing the real client."""

    def get_markets(self, *, status: str | None = ...) -> dict[str, Any]: ...


def _s(value: object) -> str | None:
    return str(value) if value is not None else None


def _mark_ts_seconds(node: object) -> int | None:
    if not isinstance(node, dict):
        return None
    ts_ms = node.get("ts_ms")
    if isinstance(ts_ms, (int, float)) and not isinstance(ts_ms, bool):
        return int(ts_ms) // 1000
    return None


def _price_of(node: object) -> str | None:
    if isinstance(node, dict):
        return _s(node.get("price"))
    return None


def _opt_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def parse_margin_market(entry: object) -> PerpMarkReadingRaw | None:
    """Turn one ``/margin/markets`` list entry into a ``PerpMarkReadingRaw``.

    Returns ``None`` (a skipped ticker, not an error) when the entry is not a
    dict, has no ticker, or has no usable ``settlement_mark_price`` with a
    timestamp — the loop needs a real ``observed_at``.
    """
    if not isinstance(entry, dict):
        return None
    ticker = entry.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        return None
    settlement = entry.get("settlement_mark_price")
    observed_at = _mark_ts_seconds(settlement)
    mark_price = _price_of(settlement)
    if observed_at is None or mark_price is None:
        return None
    try:
        if float(mark_price) <= 0:
            return None
    except (TypeError, ValueError):
        return None

    settlement_ts_ms = settlement.get("ts_ms") if isinstance(settlement, dict) else None
    return PerpMarkReadingRaw(
        market_ticker=ticker,
        observed_at=observed_at,
        settlement_mark=mark_price,
        available_at=None,  # poll loop stamps local receipt time
        reference_price=_price_of(entry.get("reference_price")),
        liquidation_mark=_price_of(entry.get("liquidation_mark_price")),
        bid=_s(entry.get("bid")),
        ask=_s(entry.get("ask")),
        contract_size=_s(entry.get("contract_size")),
        open_interest=_s(entry.get("open_interest")),
        leverage_estimate=_opt_float(entry.get("leverage_estimate")),
        extra={
            "settlement_mark_ts_ms": settlement_ts_ms,
            "asset_class": entry.get("asset_class"),
        },
    )


class KalshiPerpMarkSource:
    """``PerpMarkSource`` backed by Kalshi's ``/margin/markets`` list endpoint.

    ``fetch()`` returns the latest snapshot for each ticker in ``tickers``, or
    an empty list on a transient failure (timeout, 5xx) so ``poll_perp_marks``
    treats it as a skipped tick. An auth failure (401/403) DOES raise — a bad
    key is not transient and silently dropping every tick would be worse.
    """

    name = SOURCE_LABEL

    def __init__(
        self,
        client: _MarginMarketsClient,
        *,
        tickers: Sequence[str],
        name: str = SOURCE_LABEL,
    ) -> None:
        if not tickers:
            raise ValueError("at least one perp ticker is required")
        self._client = client
        self._wanted = set(tickers)
        self.name = name

    def fetch(self) -> Sequence[PerpMarkReadingRaw]:
        try:
            body = self._client.get_markets(status="active")
        except KalshiAuthError:
            raise
        except Exception as exc:  # transient (timeout/5xx) -> skipped tick, not a crash
            logger.warning("margin/markets fetch failed: {}", exc)
            return []

        markets = body.get("markets", []) if isinstance(body, dict) else []
        out: list[PerpMarkReadingRaw] = []
        for entry in markets:
            if isinstance(entry, dict) and entry.get("ticker") in self._wanted:
                reading = parse_margin_market(entry)
                if reading is not None:
                    out.append(reading)
        return out


__all__ = ["SOURCE_LABEL", "KalshiPerpMarkSource", "parse_margin_market"]
