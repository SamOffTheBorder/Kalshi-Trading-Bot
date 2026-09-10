"""Predeclared non-LLM baselines for underlying-market research."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class BaselineResult:
    name: str
    signal: int
    gross_return: float
    net_return: float
    tradable: bool


def no_trade_after_cost(*, gross_return: float, estimated_cost: float) -> BaselineResult:
    net = gross_return - estimated_cost
    return BaselineResult("no_trade_after_cost", 0, gross_return, net, net > 0)


def momentum_baseline(prices: Sequence[float], *, estimated_cost: float = 0.0) -> BaselineResult:
    if len(prices) < 2 or any(price <= 0 for price in prices):
        return BaselineResult("momentum", 0, 0.0, 0.0, False)
    gross = prices[-1] / prices[-2] - 1
    signal = 1 if gross > 0 else (-1 if gross < 0 else 0)
    realized = signal * gross
    return BaselineResult("momentum", signal, realized, realized - estimated_cost, signal != 0)


def naive_market_baseline(*, probability: float, outcome: bool) -> BaselineResult:
    if not 0 <= probability <= 1:
        raise ValueError("probability must be between zero and one")
    error = (probability - float(outcome)) ** 2
    return BaselineResult("naive_market", 0, -error, -error, False)


__all__ = ["BaselineResult", "momentum_baseline", "naive_market_baseline", "no_trade_after_cost"]
