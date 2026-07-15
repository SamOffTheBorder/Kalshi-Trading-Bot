"""Parse Kalshi API payloads into schema-of-record rows.

The live API (verified 2026-07-15, see the change's notes.md) returns prices
as decimal-dollar strings ("0.0100" = 1 cent) under `*_dollars` keys, and
volume/open-interest as decimal strings under `*_fp` keys. This module is the
single place that format knowledge lives.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def dollars_to_cents(value: str | None) -> int | None:
    """'0.0100' -> 1; '0.4500' -> 45. None/empty -> None."""
    if value is None or value == "":
        return None
    return round(float(value) * 100)


def fp_to_int(value: str | int | float | None) -> int:
    """'12.00' -> 12. None -> 0."""
    if value is None:
        return 0
    return round(float(value))


def iso_to_ts(value: str) -> int:
    """ISO-8601 (with Z suffix) -> epoch seconds."""
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def _ohlc(block: dict[str, Any] | None, key: str) -> int | None:
    if not block:
        return None
    return dollars_to_cents(block.get(f"{key}_dollars"))


def parse_candle(
    raw: dict[str, Any],
    *,
    market_ticker: str,
    series_ticker: str,
    period_minutes: int,
) -> dict[str, Any]:
    """API candlestick dict -> kwargs for the Candle model."""
    price = raw.get("price") or {}
    bid = raw.get("yes_bid") or {}
    ask = raw.get("yes_ask") or {}
    return {
        "market_ticker": market_ticker,
        "series_ticker": series_ticker,
        "period_minutes": period_minutes,
        "end_period_ts": raw["end_period_ts"],
        "price_open": _ohlc(price, "open"),
        "price_high": _ohlc(price, "high"),
        "price_low": _ohlc(price, "low"),
        "price_close": _ohlc(price, "close"),
        "yes_bid_open": _ohlc(bid, "open"),
        "yes_bid_high": _ohlc(bid, "high"),
        "yes_bid_low": _ohlc(bid, "low"),
        "yes_bid_close": _ohlc(bid, "close"),
        "yes_ask_open": _ohlc(ask, "open"),
        "yes_ask_high": _ohlc(ask, "high"),
        "yes_ask_low": _ohlc(ask, "low"),
        "yes_ask_close": _ohlc(ask, "close"),
        "volume": fp_to_int(raw.get("volume_fp")),
        "open_interest": fp_to_int(raw.get("open_interest_fp")),
    }


def parse_market(raw: dict[str, Any], *, series_ticker: str) -> dict[str, Any]:
    """API market dict -> kwargs for the KalshiMarket model."""
    return {
        "ticker": raw["ticker"],
        "series_ticker": series_ticker,
        "event_ticker": raw.get("event_ticker"),
        "title": raw.get("title"),
        "strike_type": raw.get("strike_type"),
        "floor_strike": raw.get("floor_strike"),
        "cap_strike": raw.get("cap_strike"),
        "open_ts": iso_to_ts(raw["open_time"]),
        "close_ts": iso_to_ts(raw["close_time"]),
        "status": raw.get("status", "unknown"),
        "result": raw.get("result") or None,
    }
