"""Named strategy registry (strategy-lab-multi-account §1).

One frozen mapping from a `strategy_id` to a constructed strategy, its
frozen config, and its declared **gate status**. The `strategy_id` an
operator passes to a paper run is the identifier that selects the
behaviour *and* the identifier recorded in the audit trail — the two can
no longer drift apart the way a free-text `--strategy-id` label could.

This module obeys `strategy/base.py`'s import rule: it sees only strategy
classes and their configs, never a data client, broker, or the execution
layer. Preflight refusal of an unknown id lives in
`execution/orchestrator.py`, which imports `KNOWN_STRATEGY_IDS` from here.

Gate status is a property of the strategy, not of any run. Nothing in the
paper path mutates it — a paper result is an input to a future gate
decision, never a substitute for one (design.md D3/D4).

    passed        cleared a pre-registered gate with margin
    gate_failed   faced a pre-registered gate and failed it
    never_gated   never faced a pre-registered gate
    parked        withdrawn from the live path; kept for comparison only

The initial statuses come from `v2-perps-scalping-and-frontend` §8, each
citing the task that established it — see `basis` on every entry.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from kalshi_bot.strategy.base import StrategyProtocol
from kalshi_bot.strategy.crypto_mispricing import (
    CryptoMispricingConfig,
    CryptoMispricingStrategy,
)
from kalshi_bot.strategy.level_break import LevelBreakConfig, LevelBreakStrategy
from kalshi_bot.strategy.settlement_prob import SettlementProbConfig, SettlementProbStrategy
from kalshi_bot.strategy.short_horizon_trend import (
    TrendConditionedConfig,
    TrendConditionedSettlementStrategy,
)
from kalshi_bot.strategy.trend_scalp import TrendScalpConfig, TrendScalpStrategy

GateStatus = Literal["passed", "gate_failed", "never_gated", "parked"]

GATE_STATUSES: frozenset[str] = frozenset(
    {"passed", "gate_failed", "never_gated", "parked"}
)


class UnknownStrategyError(KeyError):
    """Raised when a `strategy_id` is not in the registry."""


@dataclass(frozen=True)
class StrategyEntry:
    """One registry row: how to build the strategy, and where it stands."""

    strategy_id: str
    build: Callable[[], StrategyProtocol]
    config_version: str
    gate_status: GateStatus
    basis: str
    """Free text: the task or finding that set `gate_status`."""

    def construct(self) -> StrategyProtocol:
        return self.build()


def _hold_strategy() -> StrategyProtocol:
    """The default: records decisions, never enters. Not a real strategy —
    a placeholder so a run started without `--strategy` is still valid."""

    from kalshi_bot.strategy.base import Action, Decision, StrategyContext

    class _Hold:
        name = "hold"

        def evaluate(self, context: StrategyContext) -> Decision:
            return Decision(
                action=Action.HOLD,
                market_ticker=context.market_ticker,
                strategy_name=self.name,
                hold_reason="no_strategy_configured",
            )

    return _Hold()


_ENTRIES: tuple[StrategyEntry, ...] = (
    StrategyEntry(
        strategy_id="hold",
        build=_hold_strategy,
        config_version="hold-v1",
        gate_status="never_gated",
        basis="The default; never enters.",
    ),
    StrategyEntry(
        strategy_id="trend_scalp",
        build=lambda: TrendScalpStrategy(TrendScalpConfig()),
        config_version="trend_scalp-default-v1",
        gate_status="gate_failed",
        basis=(
            "v2-perps-scalping-and-frontend 8.4: 0 walk-forward test trades "
            "against the pre-registered 2026-08-18 holdout, vs the >=200-trade "
            "gate criterion."
        ),
    ),
    StrategyEntry(
        strategy_id="level_break",
        build=lambda: LevelBreakStrategy(LevelBreakConfig()),
        config_version="level_break-default-v1",
        gate_status="gate_failed",
        basis=(
            "v2-perps-scalping-and-frontend 8.4: 0 walk-forward test trades "
            "against the pre-registered 2026-08-18 holdout, vs the >=200-trade "
            "gate criterion."
        ),
    ),
    StrategyEntry(
        strategy_id="settlement_prob",
        build=lambda: SettlementProbStrategy(SettlementProbConfig()),
        config_version="settlement_prob-default-v1",
        gate_status="never_gated",
        basis=(
            "kxbtc15m-validation-rebuild: built and unit-tested; never faced a "
            "pre-registered gate (data-blocked on captured BRTI)."
        ),
    ),
    StrategyEntry(
        strategy_id="settlement_trend",
        build=lambda: TrendConditionedSettlementStrategy(TrendConditionedConfig()),
        config_version="settlement_trend-default-v1",
        gate_status="never_gated",
        basis=(
            "kxbtc15m-validation-rebuild 4.4: the settlement-aware baseline "
            'with trend drift; explicitly "NOT presumed to be an edge". Never '
            "gated."
        ),
    ),
    StrategyEntry(
        strategy_id="crypto_mispricing",
        build=lambda: CryptoMispricingStrategy(CryptoMispricingConfig()),
        config_version="crypto_mispricing-default-v1",
        gate_status="parked",
        basis=(
            'v2 proposal "Removed Capabilities": the zero-drift BS/MC pricer '
            "has no demonstrated directional edge on BTC. Kept for backtest "
            "comparison only."
        ),
    ),
)

_BY_ID: dict[str, StrategyEntry] = {e.strategy_id: e for e in _ENTRIES}

KNOWN_STRATEGY_IDS: frozenset[str] = frozenset(_BY_ID)

DEFAULT_STRATEGY_ID = "hold"


def strategy_entry(strategy_id: str) -> StrategyEntry:
    """Look up one registry entry, raising `UnknownStrategyError` if absent."""

    try:
        return _BY_ID[strategy_id]
    except KeyError as exc:
        raise UnknownStrategyError(strategy_id) from exc


def build_strategy(strategy_id: str) -> StrategyProtocol:
    """Construct the strategy named by `strategy_id`."""

    return strategy_entry(strategy_id).construct()


def all_entries() -> tuple[StrategyEntry, ...]:
    """Every registry entry, registration order."""

    return _ENTRIES


__all__ = [
    "DEFAULT_STRATEGY_ID",
    "GATE_STATUSES",
    "KNOWN_STRATEGY_IDS",
    "GateStatus",
    "StrategyEntry",
    "UnknownStrategyError",
    "all_entries",
    "build_strategy",
    "strategy_entry",
]
