"""Crypto mispricing strategy: fee gates, divergence guard, audit trail."""

import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from kalshi_bot.storage.models import Base, SignalRecord
from kalshi_bot.storage.records import record_signal
from kalshi_bot.strategy.base import Action, StrategyContext, StrategyProtocol
from kalshi_bot.strategy.crypto_mispricing import (
    CryptoMispricingConfig,
    CryptoMispricingStrategy,
    fee_adjusted_ev,
)

HOUR = 3600
NOW = 1_784_000_000


def make_context(**overrides) -> StrategyContext:
    defaults = dict(
        market_ticker="KXBTCD-TEST-T100000",
        series_ticker="KXBTCD",
        strike_type="greater",
        floor_strike=100_000.0,
        cap_strike=None,
        now_ts=NOW,
        close_ts=NOW + HOUR,
        yes_bid_cents=44,
        yes_ask_cents=46,
        spot=100_000.0,
        vol_annual=0.45,
        vol_source="historical_30d",
    )
    defaults.update(overrides)
    return StrategyContext(**defaults)


def make_strategy(**config_overrides) -> CryptoMispricingStrategy:
    cfg = CryptoMispricingConfig(mc_seed=42, mc_paths=20_000, **config_overrides)
    return CryptoMispricingStrategy(cfg)


def test_conforms_to_protocol():
    assert isinstance(make_strategy(), StrategyProtocol)


# --- fee math -----------------------------------------------------------------


def test_fee_adjusted_ev_known_answer():
    """p=0.60, c=$0.50: EV = 0.6*0.5*0.93 - 0.4*0.5 = 0.279 - 0.20 = 0.079."""
    assert fee_adjusted_ev(0.60, 0.50) == pytest.approx(0.079, abs=1e-12)


def test_fee_flips_marginal_edge_to_hold():
    """Spec scenario: raw edge positive but smaller than the fee impact -> HOLD.

    p=0.53 vs cost 0.52: raw edge +0.01, fee impact 0.07*0.53*0.48 ≈ 0.0178.
    """
    raw_edge = 0.53 - 0.52
    assert raw_edge > 0
    assert fee_adjusted_ev(0.53, 0.52) < 0

    # End-to-end: find quotes where the model's own p makes raw edge positive
    # but fee-adjusted EV negative. With min_edge tiny, only the fee blocks.
    strategy = make_strategy(min_edge=1e-9)
    # ATM-ish: bs ≈ 0.497 at these params; ask 49 -> raw edge ≈ +0.007
    ctx = make_context(yes_ask_cents=49, yes_bid_cents=48)
    decision = strategy.evaluate(ctx)
    assert decision.raw_edge is not None and decision.raw_edge > 0
    assert decision.fee_adjusted_edge is not None and decision.fee_adjusted_edge < 0
    assert decision.action == Action.HOLD
    assert decision.hold_reason == "insufficient_edge"


# --- guards ---------------------------------------------------------------------


def test_divergence_blocks_entry():
    strategy = make_strategy(max_model_divergence=1e-6)  # any MC noise trips it
    decision = strategy.evaluate(make_context())
    assert decision.action == Action.HOLD
    assert decision.hold_reason == "bs_mc_divergence"


def test_too_close_to_expiry_holds():
    decision = make_strategy().evaluate(make_context(close_ts=NOW + 5 * 60))
    assert decision.hold_reason == "too_close_to_expiry"


def test_missing_quotes_hold():
    decision = make_strategy().evaluate(make_context(yes_ask_cents=None))
    assert decision.hold_reason == "no_quotes"


def test_probability_floor_blocks_longshots():
    """Deep OTM: model p is tiny; even if the market price made EV look great,
    the probability floor blocks it."""
    strategy = make_strategy(min_edge=0.001)
    ctx = make_context(floor_strike=200_000.0, yes_ask_cents=1, yes_bid_cents=0)
    decision = strategy.evaluate(ctx)
    assert decision.action == Action.HOLD
    assert decision.hold_reason in ("probability_below_floor", "insufficient_edge")


def test_entry_fires_on_clear_mispricing():
    """Market says 30¢ for something the model prices near 50%: BUY_YES."""
    decision = make_strategy().evaluate(make_context(yes_ask_cents=30, yes_bid_cents=28))
    assert decision.action == Action.BUY_YES
    assert decision.entry_price_cents == 30
    assert decision.fee_adjusted_edge is not None and decision.fee_adjusted_edge > 0.05
    assert decision.confidence is not None and decision.confidence > 0


def test_no_side_entry_on_overpriced_yes():
    """Market says 70¢ for something the model prices near 50%: BUY_NO."""
    decision = make_strategy().evaluate(make_context(yes_ask_cents=72, yes_bid_cents=70))
    assert decision.action == Action.BUY_NO
    assert decision.entry_price_cents == 30  # 100 - yes_bid


def test_strategy_never_imports_execution_or_data():
    from pathlib import Path

    import kalshi_bot.strategy.base as base_mod
    import kalshi_bot.strategy.crypto_mispricing as strat_mod

    for mod in (base_mod, strat_mod):
        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "kalshi_bot.data" not in source
        assert "kalshi_bot.execution" not in source
        assert "httpx" not in source


# --- audit trail ------------------------------------------------------------------


def test_hold_decisions_are_persisted_with_reason():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    ctx = make_context(yes_ask_cents=None)
    decision = make_strategy().evaluate(ctx)
    record_signal(session, decision, ctx, mode="backtest")
    session.commit()

    row = session.execute(select(SignalRecord)).scalar_one()
    assert row.action == "HOLD"
    assert row.hold_reason == "no_quotes"
    stored_context = json.loads(row.context)
    assert stored_context["spot"] == 100_000.0
    assert stored_context["vol_source"] == "historical_30d"
