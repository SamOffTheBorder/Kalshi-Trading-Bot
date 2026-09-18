"""Causality-safe timestamp normalization for external market data."""

from __future__ import annotations

from typing import Literal

TimestampUnit = Literal["s", "ms", "us", "ns"]


class DataNormalizationError(ValueError):
    """Raised when a source timestamp cannot be normalized safely."""


def epoch_ms(value: int | float | str, *, unit: TimestampUnit) -> int:
    """Convert an explicitly declared source timestamp to epoch milliseconds.

    Unit is intentionally mandatory: magnitude guessing is unsafe around
    crypto data revisions and mixed spot/futures archive formats.
    """

    if isinstance(value, bool):
        raise DataNormalizationError("boolean is not a timestamp")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise DataNormalizationError(f"invalid {unit} timestamp: {value!r}") from exc
    if number < 0:
        raise DataNormalizationError("timestamp cannot be negative")
    divisor = {"s": 1, "ms": 1, "us": 1_000, "ns": 1_000_000}[unit]
    # Convert through integer arithmetic and reject sub-millisecond ambiguity
    # instead of silently rounding a non-zero remainder.
    if unit == "s":
        return number * 1_000
    if unit == "ms":
        return number
    if number % divisor:
        raise DataNormalizationError(
            f"{unit} timestamp has sub-millisecond precision: {value!r}"
        )
    return number // divisor


def causal_available_at(*, observed_at_ms: int, retrieved_at_ms: int) -> int:
    """Return the earliest defensible availability time for an observation."""

    if observed_at_ms < 0 or retrieved_at_ms < 0:
        raise DataNormalizationError("timestamps cannot be negative")
    return max(observed_at_ms, retrieved_at_ms)


__all__ = ["DataNormalizationError", "TimestampUnit", "causal_available_at", "epoch_ms"]
