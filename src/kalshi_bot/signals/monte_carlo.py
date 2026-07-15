"""Monte Carlo cross-check for digital-option probabilities.

Uses Student-t shocks (fat tails — crypto returns are not normal) instead of
normal draws, standardized to unit variance so vol input means the same thing
as in Black-Scholes. The strategy layer compares MC vs BS estimates: large
disagreement means the lognormal model is being strained (e.g., near-expiry
jump risk) and the trade is skipped.
"""

from __future__ import annotations

import math

import numpy as np

DEFAULT_PATHS = 20_000
DEFAULT_DF = 5  # degrees of freedom; ~crypto-fat tails. High df -> normal.


def terminal_spot_probability(
    *,
    spot: float,
    strike_type: str,
    floor_strike: float | None,
    cap_strike: float | None,
    vol_annual: float,
    t_years: float,
    n_paths: int = DEFAULT_PATHS,
    df: int = DEFAULT_DF,
    seed: int | None = None,
) -> float:
    """Estimate P(YES) by simulating terminal spot under GBM with
    standardized Student-t shocks."""
    if t_years <= 0:
        raise ValueError("t_years must be positive")
    if df <= 2:
        raise ValueError("df must exceed 2 for finite variance")
    rng = np.random.default_rng(seed)
    raw = rng.standard_t(df, size=n_paths)
    shocks = raw / math.sqrt(df / (df - 2))  # unit variance
    drift = -0.5 * vol_annual**2 * t_years
    terminal = spot * np.exp(drift + vol_annual * math.sqrt(t_years) * shocks)

    if strike_type == "greater":
        if floor_strike is None:
            raise ValueError("'greater' requires floor_strike")
        hits = terminal > floor_strike
    elif strike_type == "less":
        if cap_strike is None:
            raise ValueError("'less' requires cap_strike")
        hits = terminal < cap_strike
    elif strike_type == "between":
        if floor_strike is None or cap_strike is None:
            raise ValueError("'between' requires both strikes")
        hits = (terminal > floor_strike) & (terminal <= cap_strike)
    else:
        raise ValueError(f"unsupported strike_type {strike_type!r}")
    return float(np.mean(hits))
