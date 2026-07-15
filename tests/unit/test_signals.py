"""Known-answer tests for pricing math — these run before any of this code
influences a single simulated trade, let alone a real one."""

import math

import numpy as np
import pytest
from scipy.stats import norm

from kalshi_bot.signals.black_scholes import (
    contract_probability,
    digital_call_value,
    digital_range_value,
)
from kalshi_bot.signals.monte_carlo import terminal_spot_probability
from kalshi_bot.signals.volatility import (
    VolEstimate,
    estimate_volatility,
    ewma_vol,
    historical_vol,
)

# --- Black-Scholes digital: analytic known answers ---------------------------


def test_atm_digital_known_answer():
    """S=K=100, vol=0.20, T=1, r=0: d2 = -0.1, value = N(-0.1)."""
    expected = float(norm.cdf(-0.1))
    assert digital_call_value(100, 100, 0.20, 1.0) == pytest.approx(expected, abs=1e-9)


def test_digital_call_analytic_grid():
    """Independent recomputation across a grid of inputs."""
    for spot, strike, vol, t in [
        (100, 90, 0.3, 0.5),
        (50_000, 55_000, 0.6, 7 / 365),
        (2500, 2400, 0.8, 1 / 365),
        (118_000, 118_500, 0.45, 1 / (365 * 24)),
    ]:
        d2 = (math.log(spot / strike) - 0.5 * vol**2 * t) / (vol * math.sqrt(t))
        assert digital_call_value(spot, strike, vol, t) == pytest.approx(
            float(norm.cdf(d2)), abs=1e-9
        )


def test_deep_itm_approaches_one_never_exceeds():
    v = digital_call_value(200_000, 50_000, 0.4, 1 / 365)
    assert 0.999 < v <= 1.0


def test_expiry_step_function():
    assert digital_call_value(101, 100, 0.5, 0.0) == 1.0
    assert digital_call_value(99, 100, 0.5, 0.0) == 0.0
    assert digital_call_value(100, 100, 0.5, 0.0) == 0.5


def test_range_value_is_difference_of_digitals():
    lo = digital_call_value(100, 95, 0.3, 0.1)
    hi = digital_call_value(100, 105, 0.3, 0.1)
    assert digital_range_value(100, 95, 105, 0.3, 0.1) == pytest.approx(lo - hi, abs=1e-12)


def test_range_requires_ordered_strikes():
    with pytest.raises(ValueError):
        digital_range_value(100, 105, 95, 0.3, 0.1)


def test_contract_probability_less_is_complement():
    above = contract_probability(
        spot=100,
        strike_type="greater",
        floor_strike=100,
        cap_strike=None,
        vol_annual=0.2,
        t_years=0.5,
    )
    below = contract_probability(
        spot=100,
        strike_type="less",
        floor_strike=None,
        cap_strike=100,
        vol_annual=0.2,
        t_years=0.5,
    )
    assert above + below == pytest.approx(1.0, abs=1e-12)


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        digital_call_value(-1, 100, 0.2, 1.0)
    with pytest.raises(ValueError):
        digital_call_value(100, 100, 0.0, 1.0)
    with pytest.raises(ValueError):
        contract_probability(
            spot=100,
            strike_type="weird",
            floor_strike=1,
            cap_strike=2,
            vol_annual=0.2,
            t_years=0.5,
        )


# --- Monte Carlo: converges to BS under near-normal shocks ---------------------


def test_mc_converges_to_bs_with_high_df():
    """High df ~ normal shocks: MC must agree with the analytic value."""
    bs = digital_call_value(100, 105, 0.4, 0.25)
    mc = terminal_spot_probability(
        spot=100,
        strike_type="greater",
        floor_strike=105,
        cap_strike=None,
        vol_annual=0.4,
        t_years=0.25,
        n_paths=400_000,
        df=200,
        seed=42,
    )
    assert mc == pytest.approx(bs, abs=0.005)


def test_mc_fat_tails_shift_far_otm_probability():
    """Fat tails put MORE mass far out-of-the-money than lognormal."""
    bs = digital_call_value(100, 140, 0.3, 0.1)
    mc = terminal_spot_probability(
        spot=100,
        strike_type="greater",
        floor_strike=140,
        cap_strike=None,
        vol_annual=0.3,
        t_years=0.1,
        n_paths=400_000,
        df=4,
        seed=42,
    )
    assert mc > bs


def test_mc_between_matches_complement(seed=7):
    p_between = terminal_spot_probability(
        spot=100,
        strike_type="between",
        floor_strike=95,
        cap_strike=105,
        vol_annual=0.3,
        t_years=0.1,
        n_paths=200_000,
        df=5,
        seed=seed,
    )
    p_above = terminal_spot_probability(
        spot=100,
        strike_type="greater",
        floor_strike=105,
        cap_strike=None,
        vol_annual=0.3,
        t_years=0.1,
        n_paths=200_000,
        df=5,
        seed=seed,
    )
    p_above_floor = terminal_spot_probability(
        spot=100,
        strike_type="greater",
        floor_strike=95,
        cap_strike=None,
        vol_annual=0.3,
        t_years=0.1,
        n_paths=200_000,
        df=5,
        seed=seed,
    )
    assert p_between == pytest.approx(p_above_floor - p_above, abs=1e-9)


def test_mc_rejects_df_without_variance():
    with pytest.raises(ValueError):
        terminal_spot_probability(
            spot=100,
            strike_type="greater",
            floor_strike=100,
            cap_strike=None,
            vol_annual=0.3,
            t_years=0.1,
            df=2,
        )


# --- Volatility chain ---------------------------------------------------------


def _gbm_closes(n: int, vol_annual: float, seed: int = 1) -> list[float]:
    rng = np.random.default_rng(seed)
    daily = vol_annual / math.sqrt(365)
    return list(100 * np.exp(np.cumsum(rng.normal(0, daily, n))))


def test_historical_vol_recovers_known_vol():
    closes = _gbm_closes(400, 0.5)
    assert historical_vol(closes) == pytest.approx(0.5, rel=0.35)


def test_ewma_positive_and_finite():
    v = ewma_vol(_gbm_closes(20, 0.6))
    assert 0 < v < 5


def test_chain_prefers_historical():
    est = estimate_volatility(_gbm_closes(40, 0.5))
    assert est.source == "historical_30d"


def test_chain_falls_back_to_ewma():
    est = estimate_volatility(_gbm_closes(15, 0.5))
    assert est.source == "ewma"


def test_chain_falls_back_to_intraday():
    est = estimate_volatility(daily_closes=None, hourly_closes=_gbm_closes(48, 0.5))
    assert est.source == "intraday"
    assert isinstance(est, VolEstimate)


def test_chain_raises_when_no_data():
    with pytest.raises(ValueError):
        estimate_volatility([], [])


def test_nonpositive_closes_rejected():
    with pytest.raises(ValueError):
        historical_vol([100.0] * 20 + [0.0] + [100.0] * 20)
