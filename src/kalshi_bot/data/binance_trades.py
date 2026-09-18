"""Normalize Binance aggregate-trade archives with explicit aggressor semantics."""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass

from kalshi_bot.data.external_sources import ExternalInstrument
from kalshi_bot.data.normalization import TimestampUnit, causal_available_at, epoch_ms


@dataclass(frozen=True)
class NormalizedTradeInput:
    instrument: ExternalInstrument
    trade_id: str
    observed_at: int
    available_at: int
    retrieved_at: int
    price: float
    quantity: float
    aggressor_side: str | None
    parser_version: str


def normalize_aggregate_trades(
    payload: bytes,
    instrument: ExternalInstrument,
    *,
    timestamp_unit: TimestampUnit,
    retrieved_at: int,
    parser_version: str = "binance-aggtrade-v1",
) -> tuple[NormalizedTradeInput, ...]:
    """Parse Binance [id, price, qty, first, last, time, isBuyerMaker] rows."""

    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError("Binance trade artifact is not a valid ZIP") from exc
    names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    if len(names) != 1:
        raise ValueError("Binance trade ZIP must contain exactly one CSV")
    rows: list[NormalizedTradeInput] = []
    previous_id: int | None = None
    reader = csv.reader(io.StringIO(archive.read(names[0]).decode("utf-8")))
    for line_number, row in enumerate(reader, start=1):
        if not row or all(not value.strip() for value in row):
            continue
        if len(row) != 7:
            raise ValueError(f"trade row {line_number} has {len(row)} columns, expected 7")
        try:
            trade_id = int(row[0])
            price = float(row[1])
            quantity = float(row[2])
            observed_at = epoch_ms(row[5], unit=timestamp_unit)
            maker = row[6].strip().lower() == "true"
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid trade row {line_number}") from exc
        if trade_id < 0 or (previous_id is not None and trade_id <= previous_id):
            raise ValueError(f"trade IDs are not strictly increasing at row {line_number}")
        if price <= 0 or quantity <= 0:
            raise ValueError(f"trade price/quantity must be positive at row {line_number}")
        previous_id = trade_id
        available_at = causal_available_at(
            observed_at_ms=observed_at, retrieved_at_ms=retrieved_at
        )
        rows.append(
            NormalizedTradeInput(
                instrument=instrument,
                trade_id=str(trade_id),
                observed_at=observed_at,
                available_at=available_at,
                retrieved_at=retrieved_at,
                price=price,
                quantity=quantity,
                # Binance's isBuyerMaker=true means the buyer was maker, so
                # the aggressive/taker side was sell.
                aggressor_side="sell" if maker else "buy",
                parser_version=parser_version,
            )
        )
    return tuple(rows)


__all__ = ["NormalizedTradeInput", "normalize_aggregate_trades"]
