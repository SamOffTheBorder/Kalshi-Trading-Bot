"""Funding-carry strategy: known-answer tests (tasks.md 6.3/6.5)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kalshi_bot.risk.funding_awareness import FundingState, Side
from kalshi_bot.strategy.funding_carry import FundingCarryConfig, evaluate_funding_carry
from kalshi_bot.strategy.funding_carry_classification import HedgeSpec


def _eligible_hedge() -> HedgeSpec:
    """A fully-modelled linear hedge — the only kind that lets
    `evaluate_funding_carry` classify a position as market-neutral carry
    (kxbtc15m-validation-rebuild §5.2)."""
    return HedgeSpec(
        kind="perp",
        same_reference_index=True,
        rebalance_cadence_modeled=True,
        both_leg_fees_modeled=True,
        funding_accrual_modeled=True,
        residual_basis_risk_estimated=True,
    )


def _funding_state(funding_rate: float, side: Side = "long") -> FundingState:
    return FundingState(
        market_ticker="KXBTCPERP",
        next_funding_time=datetime(2026, 9, 6, 16, 0, 0, tzinfo=UTC),
        funding_rate=funding_rate,
        mark_price=50_000.0,
        side=side,
        pays_or_receives="pays" if funding_rate > 0 else "receives",
        estimated_payment_usd=funding_rate * 10_000.0,
    )


def test_funding_rate_too_small_declines():
    decision = evaluate_funding_carry(
        _funding_state(0.0001),
        position_notional_usd=10_000.0,
        config=FundingCarryConfig(min_funding_rate_abs=0.0003),
    )
    assert decision.should_enter is False
    assert decision.reason == "funding_rate_too_small"


def test_positive_funding_rate_takes_short_perp_side():
    decision = evaluate_funding_carry(
        _funding_state(0.001), position_notional_usd=10_000.0
    )
    assert decision.perp_side == "short"


def test_negative_funding_rate_takes_long_perp_side():
    decision = evaluate_funding_carry(
        _funding_state(-0.001), position_notional_usd=10_000.0
    )
    assert decision.perp_side == "long"


def test_favorable_carry_enters_with_an_eligible_linear_hedge():
    # A large notional and a big funding-rate move (funding carry is a
    # rare-event strategy per design.md/strategy-research.md — it needs an
    # extreme rate to be worth collecting at all) with a moderately-priced
    # hedge contract. Requires an ELIGIBLE linear hedge (§5.2) to enter.
    cfg = FundingCarryConfig(min_funding_rate_abs=0.0003, hedge_contract_cost_dollars=0.90)
    decision = evaluate_funding_carry(
        _funding_state(0.05),
        position_notional_usd=100_000.0,
        config=cfg,
        hedge=_eligible_hedge(),
    )
    assert decision.should_enter is True
    assert decision.market_neutral is True
    assert decision.classification_reasons == ()
    assert decision.expected_funding_usd == pytest.approx(5000.0)
    assert decision.expected_net_carry_usd is not None
    assert decision.expected_funding_usd is not None
    assert decision.expected_net_carry_usd < decision.expected_funding_usd
    assert decision.expected_net_carry_usd > 0


def test_favorable_carry_with_binary_hedge_is_disabled_not_market_neutral():
    """§5.2: the v2 prototype's default (binary event) hedge is not a linear
    hedge, so even a favourable-looking carry must NOT enter as carry."""
    cfg = FundingCarryConfig(min_funding_rate_abs=0.0003, hedge_contract_cost_dollars=0.90)
    decision = evaluate_funding_carry(
        _funding_state(0.05), position_notional_usd=100_000.0, config=cfg
    )
    assert decision.should_enter is False
    assert decision.reason == "hedge_not_linear_carry_disabled"
    assert decision.market_neutral is False
    assert any("linear" in r for r in decision.classification_reasons)
    # the research numbers are still computed
    assert decision.expected_funding_usd == pytest.approx(5000.0)
    assert decision.expected_net_carry_usd is not None


def test_unfavorable_carry_after_hedge_cost_declines():
    # Funding rate just above the minimum floor but hedge cost (cheap
    # contract -> more contracts -> more fee) eats the whole thing.
    cfg = FundingCarryConfig(
        min_funding_rate_abs=0.00001,
        hedge_contract_cost_dollars=0.50,
        min_expected_net_carry_usd=1000.0,  # deliberately unreachable gate
    )
    decision = evaluate_funding_carry(
        _funding_state(0.0002), position_notional_usd=10_000.0, config=cfg
    )
    assert decision.should_enter is False
    assert decision.reason == "net_carry_below_gate"


def test_hedge_cost_scales_with_contract_count():
    hedge = _eligible_hedge()
    cfg = FundingCarryConfig(hedge_contract_cost_dollars=0.50)
    decision_cheap = evaluate_funding_carry(
        _funding_state(0.01), position_notional_usd=10_000.0, config=cfg, hedge=hedge
    )
    cfg_expensive = FundingCarryConfig(hedge_contract_cost_dollars=0.90)
    decision_expensive = evaluate_funding_carry(
        _funding_state(0.01), position_notional_usd=10_000.0, config=cfg_expensive, hedge=hedge
    )
    # Fewer, pricier contracts needed at 0.90 than at 0.50 for the same
    # notional; fee-rate-per-contract also differs (P*(1-P) peaks at 0.50).
    assert decision_cheap.hedge_cost_usd != decision_expensive.hedge_cost_usd


def test_rejects_nonpositive_hedge_contract_cost():
    cfg = FundingCarryConfig(hedge_contract_cost_dollars=0.0)
    with pytest.raises(ValueError):
        evaluate_funding_carry(_funding_state(0.01), position_notional_usd=10_000.0, config=cfg)


def test_zero_funding_rate_declines():
    decision = evaluate_funding_carry(_funding_state(0.0), position_notional_usd=10_000.0)
    assert decision.should_enter is False
    assert decision.reason == "funding_rate_too_small"
