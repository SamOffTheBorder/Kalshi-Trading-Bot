"""Short-horizon price forecast as a numeric signal (tasks.md 7.2, design D5).

Design D5 draws a line between the per-trade *veto* (an LLM, local, fast,
fail-CLOSED — see `ai/local_review.py`) and a purpose-built *forecast*: a
time-series model that emits a number, not a chat response. This module is
the forecast side of that line.

**Structure vs. backend.** Nothing on the live path consumes a forecast yet,
and the real backend (Chronos-Bolt) needs `torch` + `chronos-forecasting`
(~2GB) that this project has not taken on. So the contract lives here now and
the model does not: `Forecaster` is a Protocol, `StubForecaster` is a
deterministic implementation good enough for wiring, tests, and backtests,
and a `ChronosForecaster` can be dropped in later without any caller
changing. The stub is honest about being a stub — it never pretends to
predict; it extrapolates the recent drift and widens an interval with the
horizon, which is a defensible naive baseline and exactly what a real model
must beat in tasks.md 7.5's benchmark.

**Fail-SAFE, not fail-closed.** Opposite of the veto on purpose. The veto
fails closed because a broken risk check must block trades. A forecast is an
additive signal: if it cannot be produced (too little history, backend
error), the right answer is "no opinion" — `ForecastSignal.neutral()`, with
`available=False` and every price field `None` — not a blocked trade and not
a crash. A strategy treats a neutral signal as zero information.

Prices throughout are the underlying's USD spot (matching `SpotCandle` /
`SpotBar`), never contract cents — this forecasts BTC, not a Kalshi price.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from math import exp, log
from typing import Protocol

from kalshi_bot.storage.models import ForecastRecord
from kalshi_bot.strategy.levels import SpotBar

DEFAULT_HORIZON_MINUTES = 15
"""KXBTC15M's window (kalshi-v2-plan-and-findings). The forecast horizon
should match the contract the signal will inform."""

DEFAULT_MIN_HISTORY_BARS = 8
"""Below this many input bars the stub refuses to forecast (fail-safe). A
real backend will have its own, likely larger, minimum context length."""

DEFAULT_LOW_QUANTILE = 0.1
DEFAULT_HIGH_QUANTILE = 0.9


@dataclass(frozen=True)
class ForecastSignal:
    """Fixed output shape. `available=False` is the neutral / no-opinion
    row: a strategy must treat it as zero information, and it is still
    persisted (see `ForecastRecord`) so an unavailable forecaster shows up
    in the data."""

    symbol: str
    asof_ts: int
    horizon_minutes: int
    last_price: float

    median_price: float | None
    low_price: float | None
    high_price: float | None
    expected_return: float | None
    """median_price / last_price - 1. None when unavailable."""

    available: bool
    reason: str  # "ok" | "insufficient_history" | "backend_error:..." | ...
    latency_ms: int | None = None

    @staticmethod
    def neutral(
        *,
        symbol: str,
        asof_ts: int,
        horizon_minutes: int,
        last_price: float,
        reason: str,
        latency_ms: int | None = None,
    ) -> ForecastSignal:
        return ForecastSignal(
            symbol=symbol,
            asof_ts=asof_ts,
            horizon_minutes=horizon_minutes,
            last_price=last_price,
            median_price=None,
            low_price=None,
            high_price=None,
            expected_return=None,
            available=False,
            reason=reason,
            latency_ms=latency_ms,
        )


class Forecaster(Protocol):
    """A backend produces a `ForecastSignal` from recent spot bars. It must
    never raise for an ordinary data problem — return
    `ForecastSignal.neutral(...)` instead — and must set `available=False`
    on any row it is not confident in."""

    name: str

    def forecast(
        self, bars: Sequence[SpotBar], *, symbol: str, horizon_minutes: int
    ) -> ForecastSignal: ...


class StubForecaster:
    """Deterministic naive-drift baseline. NOT a predictive model — a
    placeholder with honest semantics until a real backend is wired.

    Method: take the mean per-bar log return over the input window, project
    it forward `horizon_minutes` (converted to bars via the input cadence),
    and place a symmetric interval at ±(k · recent stdev · sqrt(steps)).
    This is the "random walk with drift" null hypothesis — a real model has
    to do better than this to earn its dependencies (tasks.md 7.5).
    """

    name = "stub"

    def __init__(
        self,
        *,
        min_history_bars: int = DEFAULT_MIN_HISTORY_BARS,
        interval_k: float = 1.28,  # ~10/90 quantiles under a normal
    ) -> None:
        self._min_history = min_history_bars
        self._interval_k = interval_k

    def forecast(
        self, bars: Sequence[SpotBar], *, symbol: str, horizon_minutes: int
    ) -> ForecastSignal:
        start = time.monotonic()
        bars = tuple(bars)
        last_price = bars[-1].close if bars else 0.0
        asof_ts = bars[-1].ts if bars else 0

        def _neutral(reason: str) -> ForecastSignal:
            return ForecastSignal.neutral(
                symbol=symbol,
                asof_ts=asof_ts,
                horizon_minutes=horizon_minutes,
                last_price=last_price,
                reason=reason,
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        if len(bars) < self._min_history:
            return _neutral("insufficient_history")
        if any(b.close <= 0 for b in bars):
            return _neutral("non_positive_price")

        # Per-bar log returns and their moments.
        closes = [b.close for b in bars]
        rets = [log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        mean_ret = sum(rets) / len(rets)
        var = sum((r - mean_ret) ** 2 for r in rets) / len(rets)
        stdev = var**0.5

        # Input cadence (seconds/bar) from the median gap — robust to one
        # odd gap. Fall back to a neutral row if timestamps are unusable.
        gaps = sorted(bars[i].ts - bars[i - 1].ts for i in range(1, len(bars)))
        bar_seconds = gaps[len(gaps) // 2]
        if bar_seconds <= 0:
            return _neutral("bad_bar_spacing")
        steps = max(1.0, (horizon_minutes * 60) / bar_seconds)

        median_price = last_price * exp(mean_ret * steps)
        band = self._interval_k * stdev * (steps**0.5)
        low_price = last_price * exp(mean_ret * steps - band)
        high_price = last_price * exp(mean_ret * steps + band)

        return ForecastSignal(
            symbol=symbol,
            asof_ts=asof_ts,
            horizon_minutes=horizon_minutes,
            last_price=last_price,
            median_price=median_price,
            low_price=low_price,
            high_price=high_price,
            expected_return=median_price / last_price - 1.0,
            available=True,
            reason="ok",
            latency_ms=int((time.monotonic() - start) * 1000),
        )


def to_forecast_record(
    signal: ForecastSignal, *, backend: str, signal_id: int | None = None
) -> ForecastRecord:
    """Build the persistable row for one forecast. Called unconditionally
    by the caller — available or neutral alike — for the reason in
    `ForecastRecord`'s docstring."""
    return ForecastRecord(
        signal_id=signal_id,
        backend=backend,
        symbol=signal.symbol,
        asof_ts=signal.asof_ts,
        horizon_minutes=signal.horizon_minutes,
        last_price=signal.last_price,
        median_price=signal.median_price,
        low_price=signal.low_price,
        high_price=signal.high_price,
        expected_return=signal.expected_return,
        available=signal.available,
        reason=signal.reason,
        latency_ms=signal.latency_ms,
    )


__all__ = [
    "DEFAULT_HORIZON_MINUTES",
    "DEFAULT_MIN_HISTORY_BARS",
    "ForecastSignal",
    "Forecaster",
    "StubForecaster",
    "to_forecast_record",
]
