"""Perp/event separation (kxbtc15m-validation-rebuild §5.1) and the
funding-carry classification gate (§5.2)."""

from __future__ import annotations

import pytest

from kalshi_bot.backtest.perp_ledger import (
    FundingEvent,
    PerpPromotionPolicy,
    PerpTrade,
    compute_perp_metrics,
    evaluate_perp_promotion,
)
from kalshi_bot.strategy.funding_carry_classification import (
    BINARY_EVENT_HEDGE,
    CarryClassification,
    HedgeSpec,
    classify_funding_carry,
)

# --- §5.2 classification gate --------------------------------------------


def _fully_modeled(**overrides) -> HedgeSpec:
    base = dict(
        kind="perp",
        same_reference_index=True,
        rebalance_cadence_modeled=True,
        both_leg_fees_modeled=True,
        funding_accrual_modeled=True,
        residual_basis_risk_estimated=True,
    )
    base.update(overrides)
    return HedgeSpec(**base)  # type: ignore[arg-type]


def test_binary_event_hedge_is_disabled():
    result = classify_funding_carry(BINARY_EVENT_HEDGE)
    assert result.classification is CarryClassification.DISABLED
    assert not result.eligible
    assert any("linear" in r for r in result.reasons)


def test_fully_modeled_linear_hedge_is_eligible():
    result = classify_funding_carry(_fully_modeled())
    assert result.classification is CarryClassification.ELIGIBLE
    assert result.eligible
    assert result.reasons == ()


@pytest.mark.parametrize(
    "override,needle",
    [
        ({"kind": "option"}, "linear"),
        ({"same_reference_index": False}, "reference index"),
        ({"rebalance_cadence_modeled": False}, "rollover"),
        ({"both_leg_fees_modeled": False}, "fee schedule"),
        ({"funding_accrual_modeled": False}, "per interval"),
        ({"residual_basis_risk_estimated": False}, "basis risk"),
    ],
)
def test_each_missing_component_disables_with_its_reason(override, needle):
    result = classify_funding_carry(_fully_modeled(**override))
    assert result.classification is CarryClassification.DISABLED
    assert any(needle in r for r in result.reasons)


def test_multiple_missing_components_are_all_reported():
    result = classify_funding_carry(
        _fully_modeled(funding_accrual_modeled=False, residual_basis_risk_estimated=False)
    )
    assert len(result.reasons) == 2


# --- §5.1 perp ledger is its own thing --------------------------------


def _trade(**overrides) -> PerpTrade:
    base = dict(
        symbol="BTC-PERP",
        entry_ts=1_000,
        exit_ts=2_000,
        size=1.0,
        entry_mark=60_000.0,
        exit_mark=60_600.0,
        entry_fee_usd=5.0,
        exit_fee_usd=5.0,
        funding_events=(),
        max_leverage_used=2.0,
        min_distance_to_liquidation=0.30,
    )
    base.update(overrides)
    return PerpTrade(**base)  # type: ignore[arg-type]


def test_perp_trade_pnl_components():
    t = _trade(
        funding_events=(
            FundingEvent(ts=1_500, funding_rate=0.001, position_notional_usd=60_000.0,
                         payment_usd=60.0),
        )
    )
    assert t.gross_pnl_usd == pytest.approx(600.0)  # 1.0 * (60_600 - 60_000)
    assert t.funding_pnl_usd == pytest.approx(60.0)
    assert t.fees_usd == pytest.approx(10.0)
    assert t.net_pnl_usd == pytest.approx(650.0)


def test_perp_metrics_foreground_liquidation_distance_not_win_rate():
    trades = [
        _trade(min_distance_to_liquidation=0.30),
        _trade(exit_mark=59_400.0, min_distance_to_liquidation=0.08),  # a loser, close to liq
    ]
    m = compute_perp_metrics(trades)
    assert m.n_trades == 2
    assert m.min_distance_to_liquidation == pytest.approx(0.08)
    assert m.worst_trade_pnl_usd is not None and m.worst_trade_pnl_usd < 0
    # there is deliberately no win_rate / breakeven / brier on PerpLedgerMetrics
    assert not hasattr(m, "win_rate")
    assert not hasattr(m, "brier")


def test_perp_metrics_funding_share_flags_a_mislabelled_carry():
    # net PnL is mostly PRICE move, funding is a sliver -> not real carry
    trades = [
        _trade(
            exit_mark=61_000.0,  # +1000 price move
            funding_events=(
                FundingEvent(1_500, 0.0001, 60_000.0, 6.0),
            ),
        )
    ]
    m = compute_perp_metrics(trades)
    assert m.funding_share_of_net is not None
    assert m.funding_share_of_net < 0.05  # ~6 / ~990


def test_perp_promotion_rejects_a_liquidation_regardless_of_pnl():
    trades = [_trade(min_distance_to_liquidation=-0.01) for _ in range(40)]
    m = compute_perp_metrics(trades)
    decision = evaluate_perp_promotion(m)
    assert not decision.passed
    assert any("liquidated" in r for r in decision.reasons)


def test_perp_promotion_rejects_getting_too_close_to_liquidation():
    trades = [_trade(min_distance_to_liquidation=0.05) for _ in range(40)]
    decision = evaluate_perp_promotion(compute_perp_metrics(trades))
    assert not decision.passed
    assert any("liquidation" in r for r in decision.reasons)


def test_perp_promotion_rejects_excess_leverage():
    trades = [_trade(max_leverage_used=4.0, min_distance_to_liquidation=0.30) for _ in range(40)]
    decision = evaluate_perp_promotion(compute_perp_metrics(trades))
    assert not decision.passed
    assert any("leverage" in r for r in decision.reasons)


def test_perp_promotion_passes_a_clean_book():
    trades = [
        _trade(max_leverage_used=1.8, min_distance_to_liquidation=0.25)
        for _ in range(40)
    ]
    decision = evaluate_perp_promotion(compute_perp_metrics(trades))
    assert decision.passed
    assert decision.reasons == ()


def test_perp_promotion_needs_a_minimum_sample():
    trades = [_trade() for _ in range(5)]
    decision = evaluate_perp_promotion(
        compute_perp_metrics(trades), PerpPromotionPolicy(min_trades=30)
    )
    assert not decision.passed
    assert any("perp trades" in r for r in decision.reasons)


def test_empty_perp_metrics_are_well_defined():
    m = compute_perp_metrics([])
    assert m.n_trades == 0
    assert m.min_distance_to_liquidation is None
    assert m.funding_share_of_net is None
