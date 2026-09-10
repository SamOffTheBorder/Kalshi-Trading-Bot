"""Normalize Binance kline archives without imputing missing observations."""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass

from kalshi_bot.data.external_sources import ExternalInstrument
from kalshi_bot.data.normalization import (
    DataNormalizationError,
    TimestampUnit,
    causal_available_at,
    epoch_ms,
)


@dataclass(frozen=True)
class NormalizedBarInput:
    instrument: ExternalInstrument
    period_minutes: int
    open_ts: int
    close_ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    observed_at: int
    available_at: int
    retrieved_at: int
    parser_version: str


def _interval_minutes(interval: str) -> int:
    if interval.endswith("m"):
        return int(interval[:-1])
    if interval.endswith("h"):
        return int(interval[:-1]) * 60
    if interval.endswith("d"):
        return int(interval[:-1]) * 1_440
    raise DataNormalizationError(f"unsupported Binance kline interval: {interval!r}")


def _floor_to_ms(value: str, unit: TimestampUnit) -> str:
    """Truncate a sub-millisecond close time down to whole milliseconds.

    Binance publishes an INCLUSIVE bar close -- the last representable instant
    inside the bar. In millisecond archives that is ``...59999`` (already whole
    ms), but in microsecond archives it is ``...59999999``, which is not
    millisecond-aligned and would trip the deliberate sub-millisecond guard in
    :func:`epoch_ms`.

    Flooring is the conservative direction for a *close* time: it can only move
    the observation earlier within its own bar, never later, so it cannot make
    data appear available before it truly was. Only the close column is treated
    this way; ``open_ts`` stays exact, and no other precision is inferred.
    """

    divisor = {"s": 1, "ms": 1, "us": 1_000, "ns": 1_000_000}.get(unit)
    if divisor is None or divisor == 1:
        return value
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise DataNormalizationError(f"invalid {unit} timestamp: {value!r}") from exc
    return str(number - (number % divisor))


def _archive_csv(payload: bytes) -> io.TextIOBase:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise DataNormalizationError("Binance kline artifact is not a valid ZIP") from exc
    names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    if len(names) != 1:
        raise DataNormalizationError("Binance kline ZIP must contain exactly one CSV")
    return io.StringIO(archive.read(names[0]).decode("utf-8"))


def normalize_klines(
    payload: bytes,
    instrument: ExternalInstrument,
    *,
    interval: str,
    timestamp_unit: TimestampUnit,
    retrieved_at: int,
    parser_version: str = "binance-kline-v1",
) -> tuple[NormalizedBarInput, ...]:
    """Parse Binance's 12-column kline CSV into immutable normalized values.

    ``timestamp_unit`` is explicit because Binance archive precision differs
    across datasets/eras.  It is never inferred from magnitude.
    """

    if timestamp_unit not in {"s", "ms", "us", "ns"}:
        raise DataNormalizationError(f"unsupported timestamp unit: {timestamp_unit!r}")
    if retrieved_at < 0:
        raise DataNormalizationError("retrieved_at cannot be negative")
    period = _interval_minutes(interval)
    rows: list[NormalizedBarInput] = []
    previous_open: int | None = None
    for line_number, row in enumerate(csv.reader(_archive_csv(payload)), start=1):
        if not row or all(not value.strip() for value in row):
            continue
        # Binance's USD-M futures archives ship a CSV header row; the spot
        # archives do not. Skip it by shape (non-numeric open_time) rather than
        # by position, so a headerless file is never silently truncated.
        if line_number == 1 and not row[0].strip().lstrip("-").isdigit():
            continue
        if len(row) != 12:
            raise DataNormalizationError(
                f"kline row {line_number} has {len(row)} columns, expected 12"
            )
        try:
            open_ts = epoch_ms(row[0], unit=timestamp_unit)
            close_ts = epoch_ms(_floor_to_ms(row[6], timestamp_unit), unit=timestamp_unit)
            values = tuple(float(row[index]) for index in (1, 2, 3, 4, 5))
        except (DataNormalizationError, ValueError) as exc:
            raise DataNormalizationError(f"invalid kline row {line_number}") from exc
        if close_ts < open_ts or any(value < 0 for value in values[:4]):
            raise DataNormalizationError(f"invalid kline prices/times at row {line_number}")
        if previous_open is not None and open_ts <= previous_open:
            raise DataNormalizationError(
                f"kline rows are not strictly increasing at row {line_number}"
            )
        previous_open = open_ts
        available_at = causal_available_at(observed_at_ms=close_ts, retrieved_at_ms=retrieved_at)
        rows.append(
            NormalizedBarInput(
                instrument=instrument,
                period_minutes=period,
                open_ts=open_ts,
                close_ts=close_ts,
                open=values[0],
                high=values[1],
                low=values[2],
                close=values[3],
                volume=values[4],
                observed_at=close_ts,
                available_at=available_at,
                retrieved_at=retrieved_at,
                parser_version=parser_version,
            )
        )
    return tuple(rows)


__all__ = ["NormalizedBarInput", "normalize_klines"]
