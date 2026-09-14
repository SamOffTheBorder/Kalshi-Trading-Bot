"""Strategy registry + preflight strategy-id validation
(strategy-lab-multi-account §1.5).

Covers: a known id constructs the right strategy; an unknown id fails
preflight with reason `unknown_strategy_id` and writes no run row; the
default (no `--strategy`) is the hold strategy; a paper run result does not
mutate a strategy's registry gate status.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from kalshi_bot.config.settings import Settings  # noqa: E402
from kalshi_bot.execution.orchestrator import (  # noqa: E402
    AdapterDecision,
    PaperOrchestrator,
    PaperRunConfig,
    PreflightError,
    ReconciliationOutcome,
    resolve_strategy_id,
    run_preflight,
)
from kalshi_bot.storage.db import create_all_tables  # noqa: E402
from kalshi_bot.storage.models import PaperRun  # noqa: E402
from kalshi_bot.strategy.registry import (  # noqa: E402
    DEFAULT_STRATEGY_ID,
    GATE_STATUSES,
    KNOWN_STRATEGY_IDS,
    UnknownStrategyError,
    all_entries,
    build_strategy,
    strategy_entry,
)


def _settings(**overrides):
    base = dict(
        paper_trading=True,
        kalshi_use_demo_env=True,
        db_path="paper.db",
        bankroll_total_usd=1_000.0,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    return sessionmaker(bind=engine)


# -- registry ---------------------------------------------------------------


def test_every_entry_builds_a_strategy_whose_name_is_consistent():
    for entry in all_entries():
        strat = build_strategy(entry.strategy_id)
        assert hasattr(strat, "evaluate")
        assert isinstance(strat.name, str) and strat.name


def test_every_entry_has_a_recognized_gate_status():
    for entry in all_entries():
        assert entry.gate_status in GATE_STATUSES
        assert entry.basis  # a non-empty rationale


def test_known_id_constructs_the_expected_strategy():
    strat = build_strategy("trend_scalp")
    assert type(strat).__name__ == "TrendScalpStrategy"
    strat = build_strategy("level_break")
    assert type(strat).__name__ == "LevelBreakStrategy"


def test_gate_failed_status_is_recorded_for_the_two_directional_strategies():
    # v2-perps-scalping-and-frontend 8.4 failed both on trade count.
    assert strategy_entry("trend_scalp").gate_status == "gate_failed"
    assert strategy_entry("level_break").gate_status == "gate_failed"


def test_unknown_id_raises_unknown_strategy_error():
    with pytest.raises(UnknownStrategyError):
        strategy_entry("nope")


def test_resolve_maps_legacy_sentinels_to_the_default():
    assert resolve_strategy_id("unspecified") == DEFAULT_STRATEGY_ID
    assert resolve_strategy_id("") == DEFAULT_STRATEGY_ID
    assert resolve_strategy_id("trend_scalp") == "trend_scalp"
    assert DEFAULT_STRATEGY_ID in KNOWN_STRATEGY_IDS


# -- preflight ------------------------------------------------------------


def test_preflight_refuses_an_unknown_strategy_id_with_no_run_row(session_factory):
    cfg = PaperRunConfig(
        domain="prediction",
        assets=("BTC",),
        mode="shadow",
        strategy_id="does_not_exist",
    )
    with pytest.raises(PreflightError, match="unknown_strategy_id"):
        run_preflight(_settings(), cfg)

    with session_factory() as session:
        assert session.execute(select(PaperRun)).first() is None


def _paper_lifecycle_registry():
    """The default crypto registry with ETH's instruments forced to the
    `paper` lifecycle, so preflight admits ETH and we can assert on the
    resolved strategy fields rather than hitting the no-admitted-asset path."""
    from kalshi_bot.config import crypto_registry as cr

    return tuple(
        a.model_copy(
            update={
                "event_instruments": {
                    k: v.model_copy(update={"lifecycle": "paper"})
                    for k, v in a.event_instruments.items()
                }
            }
        )
        if a.asset_id == "ETH"
        else a
        for a in cr.DEFAULT_CRYPTO_REGISTRY
    )


def test_preflight_default_resolves_to_hold(session_factory):
    cfg = PaperRunConfig(domain="prediction", assets=("ETH",), mode="shadow")
    result = run_preflight(_settings(), cfg, registry=_paper_lifecycle_registry())
    assert result.strategy_id == "hold"
    assert result.strategy_gate_status == "never_gated"
    assert result.strategy_config_version == "hold-v1"


def test_preflight_carries_gate_status_for_a_named_strategy(session_factory):
    cfg = PaperRunConfig(
        domain="prediction",
        assets=("ETH",),
        mode="shadow",
        strategy_id="trend_scalp",
    )
    result = run_preflight(_settings(), cfg, registry=_paper_lifecycle_registry())
    assert result.strategy_id == "trend_scalp"
    assert result.strategy_gate_status == "gate_failed"
    assert result.strategy_config_version == "trend_scalp-default-v1"


class _StubAdapter:
    domain = "prediction"
    broker_name = "paper"

    def __init__(self, decision):
        self._decision = decision

    def reconcile(self, asset_id):
        return ReconciliationOutcome(asset_id, True, "no_open_positions")

    def evaluate(self, asset_id, *, now_ts, may_fill):
        return self._decision


def _clock(start=0.0, step=1.0):
    t = [start - step]

    def _now():
        t[0] += step
        return t[0]

    return _now


def test_run_row_records_the_resolved_strategy_and_gate_status(session_factory):
    reg = _paper_lifecycle_registry()
    adapter = _StubAdapter(
        AdapterDecision("ETH", "prediction", "hold", "hold", reason="no_edge")
    )
    cfg = PaperRunConfig(
        domain="prediction",
        assets=("ETH",),
        mode="shadow",
        strategy_id="trend_scalp",
        duration_seconds=5,
    )
    orch = PaperOrchestrator(
        settings=_settings(),
        config=cfg,
        session_factory=session_factory,
        adapter=adapter,
        now_fn=_clock(),
        sleep_fn=lambda _s: None,
        cycle_seconds=1.0,
        registry=reg,
        max_cycles=2,
    )
    run_id = orch.run()

    with session_factory() as session:
        row = session.get(PaperRun, run_id)
        assert row is not None
        assert row.strategy_id == "trend_scalp"
        assert row.strategy_gate_status == "gate_failed"
        assert row.strategy_config_version == "trend_scalp-default-v1"

    # The run completed; the registry entry is unchanged by that outcome.
    assert strategy_entry("trend_scalp").gate_status == "gate_failed"


def test_run_row_records_hold_when_no_strategy_is_pinned(session_factory):
    reg = _paper_lifecycle_registry()
    adapter = _StubAdapter(
        AdapterDecision("ETH", "prediction", "hold", "hold", reason="no_edge")
    )
    cfg = PaperRunConfig(
        domain="prediction", assets=("ETH",), mode="shadow", duration_seconds=5
    )
    orch = PaperOrchestrator(
        settings=_settings(),
        config=cfg,
        session_factory=session_factory,
        adapter=adapter,
        now_fn=_clock(),
        sleep_fn=lambda _s: None,
        cycle_seconds=1.0,
        registry=reg,
        max_cycles=2,
    )
    run_id = orch.run()
    with session_factory() as session:
        row = session.get(PaperRun, run_id)
        assert row.strategy_id == "hold"
        assert row.strategy_gate_status == "never_gated"
