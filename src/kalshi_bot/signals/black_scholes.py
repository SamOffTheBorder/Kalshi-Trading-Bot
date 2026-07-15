"""Digital-option fair value for Kalshi binary contracts.

A "spot above K at expiry" contract is a cash-or-nothing digital call whose
fair value is N(d2). A range contract (K1 < spot < K2) is the difference of
two digitals. Rates are irrelevant at Kalshi horizons (minutes to days), so
r = 0 throughout.

Pure functions only — no I/O, no state. Successor to v1's verified
implementation, rewritten with tests against analytic values first.
"""

from __future__ import annotations

import math

from scipy.stats import norm

# Below ~30 seconds to expiry, vol math degenerates; treat as a step function.
MIN_TIME_YEARS = 1e-6


def digital_call_value(
    spot: float,
    strike: float,
    vol_annual: float,
    t_years: float,
) -> float:
    """P(spot_T > strike) under GBM with r=0. Returns a probability in [0, 1]."""
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if vol_annual <= 0:
        raise ValueError("vol_annual must be positive")
    if t_years <= MIN_TIME_YEARS:
        if spot > strike:
            return 1.0
        if spot < strike:
            return 0.0
        return 0.5
    sqrt_t = math.sqrt(t_years)
    d2 = (math.log(spot / strike) - 0.5 * vol_annual**2 * t_years) / (vol_annual * sqrt_t)
    return float(norm.cdf(d2))


def digital_range_value(
    spot: float,
    floor_strike: float,
    cap_strike: float,
    vol_annual: float,
    t_years: float,
) -> float:
    """P(floor < spot_T <= cap) = P(spot_T > floor) - P(spot_T > cap)."""
    if cap_strike <= floor_strike:
        raise ValueError("cap_strike must exceed floor_strike")
    above_floor = digital_call_value(spot, floor_strike, vol_annual, t_years)
    above_cap = digital_call_value(spot, cap_strike, vol_annual, t_years)
    return max(0.0, above_floor - above_cap)


def contract_probability(
    *,
    spot: float,
    strike_type: str,
    floor_strike: float | None,
    cap_strike: float | None,
    vol_annual: float,
    t_years: float,
) -> float:
    """Fair probability of YES for a Kalshi market row (strike_type semantics
    as returned by the API: 'greater', 'less', 'between')."""
    if strike_type == "greater":
        if floor_strike is None:
            raise ValueError("'greater' requires floor_strike")
        return digital_call_value(spot, floor_strike, vol_annual, t_years)
    if strike_type == "less":
        if cap_strike is None:
            raise ValueError("'less' requires cap_strike")
        return 1.0 - digital_call_value(spot, cap_strike, vol_annual, t_years)
    if strike_type == "between":
        if floor_strike is None or cap_strike is None:
            raise ValueError("'between' requires both strikes")
        return digital_range_value(spot, floor_strike, cap_strike, vol_annual, t_years)
    raise ValueError(f"unsupported strike_type {strike_type!r}")
