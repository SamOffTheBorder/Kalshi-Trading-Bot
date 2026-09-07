"""Parse Kalshi API payloads into schema-of-record rows.

The live API (verified 2026-07-15, see the change's notes.md) returns prices
as decimal-dollar strings ("0.0100" = 1 cent) under `*_dollars` keys, and
volume/open-interest as decimal strings under `*_fp` keys. This module is the
single place that format knowledge lives.
"""

from __future__ import annotations

import time
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def dollars_to_cents(value: str | None) -> int | None:
    """'0.0100' -> 1; '0.4500' -> 45. None/empty -> None."""
    if value is None or value == "":
        return None
    # Decimal avoids binary-float surprises at the exchange boundary.
    return int((Decimal(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


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


def _exact_ohlc(block: dict[str, Any] | None, key: str) -> str | None:
    if not block:
        return None
    value = block.get(f"{key}_dollars")
    return str(value) if value is not None and value != "" else None


def parse_candle(
    raw: dict[str, Any],
    *,
    market_ticker: str,
    series_ticker: str,
    period_minutes: int,
    observed_at: int | None = None,
    available_at: int | None = None,
    capture_session_id: str | None = None,
    source_endpoint: str | None = None,
    fetched_at: int | None = None,
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
        "observed_at": (
            observed_at if observed_at is not None else raw["end_period_ts"] - period_minutes * 60
        ),
        "available_at": available_at if available_at is not None else raw["end_period_ts"],
        "capture_session_id": capture_session_id,
        "source_endpoint": source_endpoint,
        "fetched_at": fetched_at if fetched_at is not None else int(time.time()),
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
        **{
            f"price_{key}_dollars": _exact_ohlc(price, key)
            for key in ("open", "high", "low", "close")
        },
        **{
            f"yes_bid_{key}_dollars": _exact_ohlc(bid, key)
            for key in ("open", "high", "low", "close")
        },
        **{
            f"yes_ask_{key}_dollars": _exact_ohlc(ask, key)
            for key in ("open", "high", "low", "close")
        },
        "volume": fp_to_int(raw.get("volume_fp")),
        "open_interest": fp_to_int(raw.get("open_interest_fp")),
        "volume_fp": _exact_value(raw.get("volume_fp")),
        "open_interest_fp": _exact_value(raw.get("open_interest_fp")),
    }


def _exact_value(value: Any) -> str | None:
    return str(value) if value is not None and value != "" else None


def parse_market(
    raw: dict[str, Any], *, series_ticker: str, observed_at: int | None = None,
    available_at: int | None = None, capture_session_id: str | None = None,
    source_endpoint: str | None = None, fetched_at: int | None = None,
) -> dict[str, Any]:
    """API market dict -> kwargs for the KalshiMarket model."""
    return {
        "ticker": raw["ticker"],
        "series_ticker": series_ticker,
        "event_ticker": raw.get("event_ticker"),
        "title": raw.get("title"),
        "strike_type": raw.get("strike_type"),
        "floor_strike": raw.get("floor_strike"),
        "cap_strike": raw.get("cap_strike"),
        "floor_strike_exact": _exact_value(raw.get("floor_strike")),
        "cap_strike_exact": _exact_value(raw.get("cap_strike")),
        "open_ts": iso_to_ts(raw["open_time"]),
        "close_ts": iso_to_ts(raw["close_time"]),
        "status": raw.get("status", "unknown"),
        "result": raw.get("result") or None,
        "observed_at": observed_at if observed_at is not None else int(time.time()),
        "available_at": available_at if available_at is not None else int(time.time()),
        "capture_session_id": capture_session_id,
        "source_endpoint": source_endpoint,
        "fetched_at": fetched_at if fetched_at is not None else int(time.time()),
        "provenance": {"series_filter": series_ticker},
    }
