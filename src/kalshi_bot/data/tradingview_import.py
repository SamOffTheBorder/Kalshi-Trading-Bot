"""Operator-reviewed TradingView CSV comparison importer (never primary)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import TextIOBase
from itertools import pairwise


class TradingViewImportError(ValueError):
    pass


@dataclass(frozen=True)
class TradingViewMetadata:
    symbol: str
    interval: str
    timezone: str
    export_time: str
    quote_currency: str
    provenance: str = "manual_comparison"


@dataclass(frozen=True)
class TradingViewBar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float | None


def parse_tradingview_csv(
    stream: TextIOBase, metadata: TradingViewMetadata
) -> list[TradingViewBar]:
    if metadata.provenance != "manual_comparison" or not all(
        (
            metadata.symbol,
            metadata.interval,
            metadata.timezone,
            metadata.export_time,
            metadata.quote_currency,
        )
    ):
        raise TradingViewImportError("complete manual-comparison metadata is required")
    rows = csv.DictReader(stream)
    required = {"time", "open", "high", "low", "close"}
    if not rows.fieldnames or not required <= set(rows.fieldnames):
        raise TradingViewImportError("CSV missing required columns")
    result = []
    for row in rows:
        try:
            result.append(
                TradingViewBar(
                    int(float(row["time"])),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row["volume"]) if row.get("volume") else None,
                )
            )
        except (TypeError, ValueError) as exc:
            raise TradingViewImportError("invalid numeric row") from exc
    if any(a.timestamp >= b.timestamp for a, b in pairwise(result)):
        raise TradingViewImportError("timestamps must increase")
    return result


__all__ = [
    "TradingViewBar",
    "TradingViewImportError",
    "TradingViewMetadata",
    "parse_tradingview_csv",
]
