"""Normalize Kraken historical trade CSVs without forward-filling gaps.

Kraken's public trade export has columns ``price, volume, time[, ...]`` with
fractional-second Unix timestamps and no native trade ID, unlike Binance's
aggTrades archives. A trade ID is synthesized deterministically from the row
content so every row still has a stable identity for the normalized-trade
unique constraint, without fabricating information Kraken never published.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass

from kalshi_bot.data.external_sources import ExternalInstrument
from kalshi_bot.data.normalization import causal_available_at


class KrakenTradeParseError(ValueError):
    """Raised when a Kraken trade CSV cannot be safely normalized."""


@dataclass(frozen=True)
class NormalizedKrakenTrade:
    instrument: ExternalInstrument
    trade_id: str
    observed_at: int
    available_at: int
    retrieved_at: int
    price: float
    quantity: float
    parser_version: str


def _synthetic_trade_id(
    *, native_symbol: str, time_raw: str, price_raw: str, volume_raw: str
) -> str:
    payload = "|".join((native_symbol, time_raw, price_raw, volume_raw))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _parse_seconds_to_ms(value: str) -> int:
    """Parse Kraken's fractional-second timestamp into whole milliseconds."""
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise KrakenTradeParseError(f"invalid Kraken trade timestamp: {value!r}") from exc
    if seconds < 0:
        raise KrakenTradeParseError("timestamp cannot be negative")
    return round(seconds * 1_000)


def normalize_kraken_trades(
    payload: bytes,
    instrument: ExternalInstrument,
    *,
    retrieved_at: int,
    parser_version: str = "kraken-trade-v1",
) -> tuple[NormalizedKrakenTrade, ...]:
    """Parse Kraken ``price, volume, time[, ...]`` rows into typed trades."""

    if instrument.source != "kraken" or instrument.source_role != "constituent":
        raise KrakenTradeParseError("normalization requires a constituent Kraken instrument")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KrakenTradeParseError("Kraken trade artifact is not valid UTF-8 text") from exc
    reader = csv.reader(io.StringIO(text))
    rows: list[NormalizedKrakenTrade] = []
    previous_observed_at: int | None = None
    for line_number, row in enumerate(reader, start=1):
        if not row or all(not value.strip() for value in row):
            continue
        if len(row) < 3:
            raise KrakenTradeParseError(
                f"trade row {line_number} has {len(row)} columns, expected at least 3"
            )
        price_raw, volume_raw, time_raw = row[0], row[1], row[2]
        try:
            price = float(price_raw)
            quantity = float(volume_raw)
        except (TypeError, ValueError) as exc:
            raise KrakenTradeParseError(f"invalid trade row {line_number}") from exc
        observed_at = _parse_seconds_to_ms(time_raw)
        if price <= 0 or quantity <= 0:
            raise KrakenTradeParseError(
                f"trade price/quantity must be positive at row {line_number}"
            )
        if previous_observed_at is not None and observed_at < previous_observed_at:
            raise KrakenTradeParseError(
                f"trade timestamps are not monotonic at row {line_number}"
            )
        previous_observed_at = observed_at
        available_at = causal_available_at(
            observed_at_ms=observed_at, retrieved_at_ms=retrieved_at
        )
        rows.append(
            NormalizedKrakenTrade(
                instrument=instrument,
                trade_id=_synthetic_trade_id(
                    native_symbol=instrument.native_symbol,
                    time_raw=time_raw,
                    price_raw=price_raw,
                    volume_raw=volume_raw,
                ),
                observed_at=observed_at,
                available_at=available_at,
                retrieved_at=retrieved_at,
                price=price,
                quantity=quantity,
                parser_version=parser_version,
            )
        )
    return tuple(rows)


__all__ = ["KrakenTradeParseError", "NormalizedKrakenTrade", "normalize_kraken_trades"]
