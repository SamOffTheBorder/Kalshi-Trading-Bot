"""Coverage and source-lag summaries for normalized external observations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise


@dataclass(frozen=True)
class CoverageReport:
    source: str
    native_symbol: str
    observation_type: str
    rows: int
    first_observed_at: int | None
    last_observed_at: int | None
    gaps: tuple[tuple[int, int], ...]
    rejected_rows: int = 0
    max_source_lag_ms: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "native_symbol": self.native_symbol,
            "observation_type": self.observation_type,
            "rows": self.rows,
            "first_observed_at": self.first_observed_at,
            "last_observed_at": self.last_observed_at,
            "gaps": [list(gap) for gap in self.gaps],
            "rejected_rows": self.rejected_rows,
            "max_source_lag_ms": self.max_source_lag_ms,
        }


def coverage_report(
    observed_at: Iterable[int],
    *,
    source: str,
    native_symbol: str,
    observation_type: str,
    expected_step: int | None = None,
    rejected_rows: int = 0,
    available_at: Iterable[int] | None = None,
) -> CoverageReport:
    values = sorted(set(observed_at))
    gaps: list[tuple[int, int]] = []
    if expected_step and expected_step > 0:
        gaps = [
            (previous + expected_step, current)
            for previous, current in pairwise(values)
            if current - previous > expected_step
        ]
    lags = []
    if available_at is not None:
        lags = [
            available - observed
            for observed, available in zip(values, available_at, strict=True)
        ]
    return CoverageReport(
        source=source,
        native_symbol=native_symbol,
        observation_type=observation_type,
        rows=len(values),
        first_observed_at=values[0] if values else None,
        last_observed_at=values[-1] if values else None,
        gaps=tuple(gaps),
        rejected_rows=rejected_rows,
        max_source_lag_ms=max(lags) if lags else None,
    )


__all__ = ["CoverageReport", "coverage_report"]
