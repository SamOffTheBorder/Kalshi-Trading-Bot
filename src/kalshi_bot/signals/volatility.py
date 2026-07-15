"""Annualized volatility estimation with a labeled fallback chain.

Priority: 30-day historical -> EWMA -> intraday realized. Each estimator
falls back to the next when it lacks data, and the result carries its source
label so downstream (and the audit trail) always know which estimate was used.

Crypto trades every day: annualization uses 365, not 252.

Pure functions over close-price sequences — callers fetch data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

TRADING_DAYS = 365
HOURS_PER_YEAR = 365 * 24

MIN_DAILY_FOR_HISTORICAL = 30
MIN_DAILY_FOR_EWMA = 10
MIN_HOURLY_FOR_INTRADAY = 24


@dataclass(frozen=True)
class VolEstimate:
    vol_annual: float
    source: str  # historical_30d | ewma | intraday


def _log_returns(closes: list[float] | np.ndarray) -> np.ndarray:
    arr = np.asarray(closes, dtype=float)
    if np.any(arr <= 0):
        raise ValueError("closes must be positive")
    return np.diff(np.log(arr))


def historical_vol(daily_closes: list[float], window_days: int = 30) -> float:
    """Std of the last `window_days` daily log returns, annualized."""
    returns = _log_returns(daily_closes)[-window_days:]
    if len(returns) < window_days - 1:
        raise ValueError(f"need >= {window_days} daily closes")
    return float(np.std(returns, ddof=1) * math.sqrt(TRADING_DAYS))


def ewma_vol(daily_closes: list[float], halflife_days: float = 10.0) -> float:
    """Exponentially-weighted vol of daily log returns, annualized."""
    returns = _log_returns(daily_closes)
    if len(returns) < MIN_DAILY_FOR_EWMA - 1:
        raise ValueError(f"need >= {MIN_DAILY_FOR_EWMA} daily closes")
    lam = 0.5 ** (1.0 / halflife_days)
    weights = lam ** np.arange(len(returns) - 1, -1, -1)
    weights /= weights.sum()
    variance = float(np.sum(weights * returns**2))
    return math.sqrt(variance * TRADING_DAYS)


def intraday_vol(hourly_closes: list[float]) -> float:
    """Realized vol from hourly log returns, annualized."""
    returns = _log_returns(hourly_closes)
    if len(returns) < MIN_HOURLY_FOR_INTRADAY - 1:
        raise ValueError(f"need >= {MIN_HOURLY_FOR_INTRADAY} hourly closes")
    return float(np.std(returns, ddof=1) * math.sqrt(HOURS_PER_YEAR))


def estimate_volatility(
    daily_closes: list[float] | None,
    hourly_closes: list[float] | None = None,
) -> VolEstimate:
    """Walk the fallback chain; raise only if no estimator has enough data."""
    daily = daily_closes or []
    hourly = hourly_closes or []
    if len(daily) >= MIN_DAILY_FOR_HISTORICAL + 1:
        return VolEstimate(historical_vol(daily), "historical_30d")
    if len(daily) >= MIN_DAILY_FOR_EWMA:
        return VolEstimate(ewma_vol(daily), "ewma")
    if len(hourly) >= MIN_HOURLY_FOR_INTRADAY:
        return VolEstimate(intraday_vol(hourly), "intraday")
    raise ValueError(
        f"insufficient data for any volatility estimator "
        f"({len(daily)} daily, {len(hourly)} hourly closes)"
    )
