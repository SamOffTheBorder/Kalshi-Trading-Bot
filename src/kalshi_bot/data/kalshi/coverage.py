"""Per-series candle coverage report (spec: kalshi-market-data).

Answers "can this series support a meaningful out-of-sample split?" before a
backtest runs. Coverage is defined over the union of candle timestamps across
all of a series' markets: a gap is a period-length hole with no candle from
any market in the series.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from kalshi_bot.storage.models import Candle


@dataclass
class CoverageReport:
    series_ticker: str
    period_minutes: int
    first_ts: int | None
    last_ts: int | None
    total_candles: int
    distinct_periods: int
    gaps: list[tuple[int, int]] = field(default_factory=list)  # (gap_start_ts, gap_end_ts)

    @property
    def first_dt(self) -> str:
        return _fmt(self.first_ts)

    @property
    def last_dt(self) -> str:
        return _fmt(self.last_ts)

    def summary(self) -> str:
        return (
            f"{self.series_ticker} @{self.period_minutes}m: "
            f"{self.total_candles} candles over {self.distinct_periods} periods, "
            f"{self.first_dt} .. {self.last_dt}, {len(self.gaps)} gaps"
        )


def _fmt(ts: int | None) -> str:
    if ts is None:
        return "-"
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M")


def coverage_report(
    session: Session, series_ticker: str, period_minutes: int = 60
) -> CoverageReport:
    ts_rows = (
        session.execute(
            select(distinct(Candle.end_period_ts))
            .where(
                Candle.series_ticker == series_ticker,
                Candle.period_minutes == period_minutes,
            )
            .order_by(Candle.end_period_ts)
        )
        .scalars()
        .all()
    )
    total = (
        session.execute(
            select(Candle.id).where(
                Candle.series_ticker == series_ticker,
                Candle.period_minutes == period_minutes,
            )
        )
        .scalars()
        .all()
    )
    gaps: list[tuple[int, int]] = []
    period_s = period_minutes * 60
    for prev, cur in itertools.pairwise(ts_rows):
        if cur - prev > period_s:
            gaps.append((prev, cur))
    return CoverageReport(
        series_ticker=series_ticker,
        period_minutes=period_minutes,
        first_ts=ts_rows[0] if ts_rows else None,
        last_ts=ts_rows[-1] if ts_rows else None,
        total_candles=len(total),
        distinct_periods=len(ts_rows),
        gaps=gaps,
    )
