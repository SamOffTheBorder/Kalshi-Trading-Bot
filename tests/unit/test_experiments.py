"""§4.5 experiments are all deferred until their data exists — the report
must be able to list them explicitly rather than silently skipping."""

from __future__ import annotations

from kalshi_bot.strategy.experiments import (
    ALL_EXPERIMENTS,
    deferred_experiments,
)


def test_all_three_experiments_are_present():
    names = {e.name for e in ALL_EXPERIMENTS}
    assert names == {"microprice", "public_trade_imbalance", "quarter_hour_open_effect"}


def test_none_are_available_yet_and_each_states_why():
    for e in ALL_EXPERIMENTS:
        assert e.available is False
        assert e.reason  # non-empty explanation


def test_deferred_experiments_returns_all_of_them_for_now():
    assert deferred_experiments() == ALL_EXPERIMENTS
