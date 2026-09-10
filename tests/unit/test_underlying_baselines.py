import pytest

from kalshi_bot.backtest.underlying_baselines import (
    momentum_baseline,
    naive_market_baseline,
    no_trade_after_cost,
)


def test_baselines_are_predeclared_and_cost_aware():
    assert no_trade_after_cost(gross_return=0.01, estimated_cost=0.02).tradable is False
    result = momentum_baseline([100, 110], estimated_cost=0.01)
    assert result.name == "momentum" and result.signal == 1
    assert result.net_return == pytest.approx(0.09)
    assert naive_market_baseline(probability=0.6, outcome=True).gross_return == pytest.approx(-0.16)


def test_baselines_fail_closed_on_invalid_inputs():
    assert momentum_baseline([100]).tradable is False
    with pytest.raises(ValueError):
        naive_market_baseline(probability=2, outcome=True)
