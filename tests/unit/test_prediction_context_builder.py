"""`StrategyContextBuilder` causal assembly + the Decision -> fill path
(strategy-lab-multi-account §2.6, §3).

Covers: a BRTI reading whose `available_at` is after `now_ts` is excluded;
a spot bar at or after `now_ts` is excluded; insufficient spot history
yields `trend_zscore=None` and a sentinel `spot`; a `StrategyProtocol`
BUY decision produces a fill when `may_fill` and a recorded no-fill
decision when not; and the reconstructed-manifest boundary still refuses
the fill regardless of the strategy signalling entry.
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
    PaperOrchestrator,
    PaperRunConfig,
)
from kalshi_bot.execution.prediction_adapter import (  # noqa: E402
    PredictionPaperAdapter,
    PredictionQuote,
    StrategyContextBuilder,
    registry_quote_source,
)
from kalshi_bot.storage.db import create_all_tables  # noqa: E402
from kalshi_bot.storage.models import (  # noqa: E402
    BRTIObservation,
    SimulatedTrade,
    SpotCandle,
)
from kalshi_bot.strategy.base import Action, Decision, StrategyContext  # noqa: E402


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    return sessionmaker(bind=engine)


def _settings(**overrides):
    base = dict(
        paper_trading=True,
        kalshi_use_demo_env=True,
        db_path="paper.db",
        bankroll_total_usd=1_000.0,
    )
    base.update(overrides)
    return Settings(**base)


def _clock(start=0.0, step=1.0):
    t = [start - step]

    def _now():
        t[0] += step
        return t[0]

    return _now


def _paper_lifecycle_registry(asset="ETH"):
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
        if a.asset_id == asset
        else a
        for a in cr.DEFAULT_CRYPTO_REGISTRY
    )


def _quote(asset="BTC", *, observed_at=10_000, close_ts=10_900):
    return PredictionQuote(
        asset_id=asset,
        market_ticker=f"KX{asset}15M-T1",
        series_ticker=f"KX{asset}15M",
        close_ts=close_ts,
        observed_at=observed_at,
        yes_bid_cents=40,
        yes_ask_cents=42,
        strike_type="greater",
        floor_strike=50_000.0,
    )


# -- causal assembly ------------------------------------------------------


def test_brti_reading_after_now_ts_is_excluded(session_factory):
    with session_factory() as session:
        session.add_all(
            [
                BRTIObservation(
                    observed_at=9_500, available_at=9_500,
                    value_dollars="50000.00", source="brti",
                ),
                BRTIObservation(
                    observed_at=10_050, available_at=10_050,  # AFTER now_ts
                    value_dollars="50010.00", source="brti",
                ),
            ]
        )
        session.commit()
        builder = StrategyContextBuilder(session)
        ctx = builder.build(_quote(), now_ts=10_000)
        usable = [r for r in ctx.brti_readings]
        assert len(usable) == 1
        assert usable[0].observed_at == 9_500
        assert all(r.usable_at <= 10_000 for r in usable)


def test_spot_bar_at_or_after_now_ts_is_excluded(session_factory):
    with session_factory() as session:
        for open_ts, close in [(3_600, 100.0), (7_200, 101.0), (10_000, 102.0)]:
            session.add(
                SpotCandle(
                    exchange="coinbase", symbol="BTC-USD", period_minutes=60,
                    open_ts=open_ts, open=close, high=close, low=close,
                    close=close, volume=1.0,
                )
            )
        session.commit()
        builder = StrategyContextBuilder(session)
        ctx = builder.build(_quote(), now_ts=10_000)
        bar_ts = [b.ts for b in ctx.spot_bars]
        assert 10_000 not in bar_ts
        assert bar_ts == [3_600, 7_200]


def test_insufficient_spot_history_yields_none_trend_and_sentinel_spot(session_factory):
    with session_factory() as session:
        builder = StrategyContextBuilder(session)
        ctx = builder.build(_quote(), now_ts=10_000)
        assert ctx.trend_zscore is None
        assert ctx.spot == 0.0
        assert ctx.vol_source == "unavailable"
        assert ctx.spot_bars == ()


def test_unknown_asset_symbol_still_builds_a_context(session_factory):
    with session_factory() as session:
        builder = StrategyContextBuilder(session)
        ctx = builder.build(_quote(asset="DOGE"), now_ts=10_000)
        assert isinstance(ctx, StrategyContext)
        assert ctx.spot == 0.0
        assert ctx.trend_zscore is None


# -- Decision -> fill path ---------------------------------------------


class _AlwaysBuy:
    name = "always_buy"

    def evaluate(self, context: StrategyContext) -> Decision:
        return Decision(
            action=Action.BUY_YES,
            market_ticker=context.market_ticker,
            strategy_name=self.name,
            fair_probability=0.6,
            entry_price_cents=context.yes_ask_cents,
        )


def _run(session_factory, *, registry, may_fill_mode, frozen_report_present,
         manifest_provenance=None):
    quote = _quote(asset="ETH", observed_at=100, close_ts=1_000)
    session = session_factory()
    adapter = PredictionPaperAdapter(
        session=session,
        quote_source=registry_quote_source({"ETH": quote}),
        settlement_source=lambda _t: None,
        starting_cash_usd=1_000.0,
        strategy=_AlwaysBuy(),
        registry=registry,
    )
    cfg = PaperRunConfig(
        domain="prediction", assets=("ETH",), mode=may_fill_mode,
        strategy_id="hold",  # registry id; the injected _AlwaysBuy is what runs
    )
    orch = PaperOrchestrator(
        settings=_settings(),
        config=cfg,
        session_factory=session_factory,
        adapter=adapter,
        now_fn=_clock(start=100.0, step=0.0),
        sleep_fn=lambda _s: None,
        cycle_seconds=1.0,
        registry=registry,
        max_cycles=1,
        frozen_report_present=frozen_report_present,
        manifest_provenance=manifest_provenance,
    )
    run_id = orch.run()
    return run_id


def test_buy_decision_fills_when_may_fill(session_factory):
    _run(
        session_factory,
        registry=_paper_lifecycle_registry("ETH"),
        may_fill_mode="paper",
        frozen_report_present=True,
    )
    with session_factory() as session:
        trades = list(
            session.execute(
                select(SimulatedTrade).where(SimulatedTrade.mode == "paper")
            ).scalars()
        )
    assert len(trades) == 1
    assert trades[0].market_ticker == "KXETH15M-T1"


def test_buy_decision_records_no_fill_in_shadow_mode(session_factory):
    _run(
        session_factory,
        registry=_paper_lifecycle_registry("ETH"),
        may_fill_mode="shadow",
        frozen_report_present=True,
    )
    with session_factory() as session:
        trades = list(
            session.execute(
                select(SimulatedTrade).where(SimulatedTrade.mode == "paper")
            ).scalars()
        )
    assert trades == []


def test_buy_decision_records_no_fill_for_reconstructed_manifest(session_factory):
    """§3.1: a real BUY decision on a run backed by a `reconstructed`
    manifest records the decision and creates no fill."""
    _run(
        session_factory,
        registry=_paper_lifecycle_registry("ETH"),
        may_fill_mode="paper",
        frozen_report_present=True,
        manifest_provenance=lambda _a: "reconstructed",
    )
    with session_factory() as session:
        trades = list(
            session.execute(
                select(SimulatedTrade).where(SimulatedTrade.mode == "paper")
            ).scalars()
        )
    assert trades == []


def test_source_native_manifest_lets_the_same_decision_fill(session_factory):
    """§3.2: the refusal above is attributable to provenance, not to the
    strategy failing to signal — a `source_native` manifest fills."""
    _run(
        session_factory,
        registry=_paper_lifecycle_registry("ETH"),
        may_fill_mode="paper",
        frozen_report_present=True,
        manifest_provenance=lambda _a: "source_native",
    )
    with session_factory() as session:
        trades = list(
            session.execute(
                select(SimulatedTrade).where(SimulatedTrade.mode == "paper")
            ).scalars()
        )
    assert len(trades) == 1
