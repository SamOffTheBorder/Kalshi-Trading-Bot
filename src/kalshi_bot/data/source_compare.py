"""Diagnostics comparing independent source series without merging them."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import fabs


@dataclass(frozen=True)
class SourcePoint:
    source: str
    native_symbol: str
    quote_currency: str
    observed_at: int
    close: float
    available_at: int


@dataclass(frozen=True)
class SourceComparison:
    left_source: str
    right_source: str
    left_symbol: str
    right_symbol: str
    quote_compatible: bool
    aligned_rows: int
    left_only_rows: int
    right_only_rows: int
    mean_abs_price_difference: float | None
    max_abs_price_difference: float | None
    max_availability_lag: int | None
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "left_source": self.left_source,
            "right_source": self.right_source,
            "left_symbol": self.left_symbol,
            "right_symbol": self.right_symbol,
            "quote_compatible": self.quote_compatible,
            "aligned_rows": self.aligned_rows,
            "left_only_rows": self.left_only_rows,
            "right_only_rows": self.right_only_rows,
            "mean_abs_price_difference": self.mean_abs_price_difference,
            "max_abs_price_difference": self.max_abs_price_difference,
            "max_availability_lag": self.max_availability_lag,
            "warnings": list(self.warnings),
        }


def compare_sources(
    left: Iterable[SourcePoint], right: Iterable[SourcePoint]
) -> SourceComparison:
    left_rows = tuple(left)
    right_rows = tuple(right)
    if not left_rows or not right_rows:
        raise ValueError("source comparison requires both series")
    left_by_ts = {row.observed_at: row for row in left_rows}
    right_by_ts = {row.observed_at: row for row in right_rows}
    common = sorted(left_by_ts.keys() & right_by_ts.keys())
    differences = [fabs(left_by_ts[ts].close - right_by_ts[ts].close) for ts in common]
    lags = [
        abs(left_by_ts[ts].available_at - right_by_ts[ts].available_at)
        for ts in common
    ]
    quote_compatible = left_rows[0].quote_currency == right_rows[0].quote_currency
    warnings: list[str] = []
    if not quote_compatible:
        warnings.append("quote_currency_mismatch")
    if len(common) < min(len(left_rows), len(right_rows)):
        warnings.append("coverage_mismatch")
    return SourceComparison(
        left_source=left_rows[0].source,
        right_source=right_rows[0].source,
        left_symbol=left_rows[0].native_symbol,
        right_symbol=right_rows[0].native_symbol,
        quote_compatible=quote_compatible,
        aligned_rows=len(common),
        left_only_rows=len(left_by_ts.keys() - right_by_ts.keys()),
        right_only_rows=len(right_by_ts.keys() - left_by_ts.keys()),
        mean_abs_price_difference=sum(differences) / len(differences) if differences else None,
        max_abs_price_difference=max(differences) if differences else None,
        max_availability_lag=max(lags) if lags else None,
        warnings=tuple(warnings),
    )


__all__ = ["SourceComparison", "SourcePoint", "compare_sources"]
