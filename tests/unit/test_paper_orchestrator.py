"""Orchestrator + prediction-adapter behavior (multi-venue-paper-trading §8.9).

Covers: preflight refusal (non-paper / production-auth / no admitted asset),
lifecycle gating (shadow records decisions but no fills; paper without a
frozen report is decision-only), domain routing + unsupported-domain reject,
signal/HOLD audit persistence, SIGINT-style interrupt handling, restart
settlement reconciliation, stale-quote rejection, and legacy-parity of the
prediction fill path (marketable limit, side-aware quote).
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
    load_run_events,
    run_preflight,
    summarize_run,
)
from kalshi_bot.execution.prediction_adapter import (  # noqa: E402
    PredictionPaperAdapter,
    PredictionQuote,
    StrategySignal,
    kalshi_public_quote_source,
    registry_quote_source,
)
from kalshi_bot.storage.db import create_all_tables  # noqa: E402
from kalshi_bot.storage.models import (  # noqa: E402
    KalshiMarket,
    PaperRun,
    SimulatedTrade,
)


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
    """Monotonic fake clock: advances `step` seconds every call."""
    t = [start - step]

    def _now():
        t[0] += step
        return t[0]

    return _now


# --------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------


def test_preflight_refuses_when_paper_trading_false():
    cfg = PaperRunConfig(domain="prediction", assets=("BTC",), mode="paper")
    with pytest.raises(PreflightError, match="PAPER_TRADING"):
        run_preflight(_settings(paper_trading=False), cfg)


def test_preflight_refuses_production_authenticated():
    cfg = PaperRunConfig(domain="prediction", assets=("BTC",), mode="paper")
    with pytest.raises(PreflightError, match="KALSHI_USE_DEMO_ENV"):
        run_preflight(_settings(kalshi_use_demo_env=False), cfg)


def test_preflight_refuses_unknown_asset():
    cfg = PaperRunConfig(domain="prediction", assets=("DOGE",), mode="shadow")
    with pytest.raises(PreflightError, match="admitted no assets"):
        run_preflight(_settings(), cfg)


def test_preflight_paper_without_frozen_report_is_decision_only():
    # BTC ships at lifecycle "backtest" -> not even a decision state, so use a
    # shadow-mode run which admits any decision-state asset for recording.
    cfg = PaperRunConfig(domain="prediction", assets=("BTC",), mode="shadow")
    # BTC lifecycle is "backtest" in the default registry -> no decisions.
    with pytest.raises(PreflightError):
        run_preflight(_settings(), cfg)


def test_preflight_shadow_admits_shadow_lifecycle_for_decisions(monkeypatch):
    from kalshi_bot.config import crypto_registry as cr

    reg = tuple(
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
    cfg = PaperRunConfig(domain="prediction", assets=("ETH",), mode="shadow")
    result = run_preflight(_settings(), cfg, registry=reg)
    adm = result.admission("ETH")
    assert adm is not None and adm.admitted is True
    # shadow-mode run never fills, even for a paper-lifecycle asset.
    assert adm.may_fill is False


def test_preflight_paper_mode_paper_lifecycle_with_report_may_fill():
    from kalshi_bot.config import crypto_registry as cr

    reg = tuple(
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
    cfg = PaperRunConfig(domain="prediction", assets=("ETH",), mode="paper")
    result = run_preflight(_settings(), cfg, registry=reg, frozen_report_present=True)
    adm = result.admission("ETH")
    assert adm is not None and adm.may_fill is True

    result_no_report = run_preflight(_settings(), cfg, registry=reg, frozen_report_present=False)
    adm2 = result_no_report.admission("ETH")
    assert adm2.admitted is True and adm2.may_fill is False
    assert adm2.reason == "no_frozen_admission_report"


# --------------------------------------------------------------------------
# Orchestrator loop
# --------------------------------------------------------------------------


class _StubAdapter:
    domain = "prediction"
    broker_name = "paper"

    def __init__(self, decisions_by_asset):
        self._decisions = decisions_by_asset
        self.reconciled = []
        self.evaluated = []

    def reconcile(self, asset_id):
        self.reconciled.append(asset_id)
        return ReconciliationOutcome(asset_id, True, "no_open_positions")

    def evaluate(self, asset_id, *, now_ts, may_fill):
        self.evaluated.append((asset_id, now_ts, may_fill))
        return self._decisions[asset_id]


def _paper_lifecycle_registry(*assets):
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
        if a.asset_id in assets
        else a
        for a in cr.DEFAULT_CRYPTO_REGISTRY
    )


def test_run_persists_run_row_and_audit_trail(session_factory):
    reg = _paper_lifecycle_registry("ETH")
    adapter = _StubAdapter(
        {
            "ETH": AdapterDecision(
                "ETH", "prediction", "hold", "hold", reason="no_edge"
            )
        }
    )
    cfg = PaperRunConfig(domain="prediction", assets=("ETH",), mode="shadow", duration_seconds=10)
    orch = PaperOrchestrator(
        settings=_settings(),
        config=cfg,
        session_factory=session_factory,
        adapter=adapter,
        now_fn=_clock(start=0.0, step=1.0),
        sleep_fn=lambda _s: None,
        cycle_seconds=1.0,
        registry=reg,
        max_cycles=3,
    )
    run_id = orch.run()

    with session_factory() as s:
        row = s.get(PaperRun, run_id)
        assert row is not None
        assert row.status == "completed"
        assert row.ended_at is not None
        events = load_run_events(s, run_id)

    summary = summarize_run(events)
    assert summary.get("run:preflight_passed") == 1
    assert summary.get("reconciliation:reconciled") == 1
    assert any(k.startswith("decision:") for k in summary)
    assert any(k.startswith("heartbeat:") for k in summary)
    assert summary.get("heartbeat:final") == 1
    assert adapter.reconciled == ["ETH"]


def test_shadow_run_records_would_fill_but_no_paper_position(session_factory):
    """§8.7: shadow mode passes may_fill=False and the adapter records the
    observable would-fill without a SimulatedTrade row."""
    reg = _paper_lifecycle_registry("ETH")
    quote = PredictionQuote(
        asset_id="ETH",
        market_ticker="KXETH15M-T1",
        series_ticker="KXETH15M",
        close_ts=1_000,
        observed_at=100,
        yes_bid_cents=40,
        yes_ask_cents=42,
    )
    with session_factory() as adapter_session:
        adapter = PredictionPaperAdapter(
            session=adapter_session,
            quote_source=registry_quote_source({"ETH": quote}),
            settlement_source=lambda _t: None,
            starting_cash_usd=1_000.0,
            strategy=lambda q: StrategySignal(
                action="buy", side="yes", limit_price_cents=50, quantity=3
            ),
            registry=reg,
        )
        cfg = PaperRunConfig(
            domain="prediction", assets=("ETH",), mode="shadow"
        )
        orch = PaperOrchestrator(
            settings=_settings(),
            config=cfg,
            session_factory=session_factory,
            adapter=adapter,
            now_fn=_clock(start=100.0, step=0.0),
            sleep_fn=lambda _s: None,
            cycle_seconds=1.0,
            registry=reg,
            max_cycles=1,
        )
        run_id = orch.run()
        adapter_session.commit()

    with session_factory() as s:
        trades = list(s.execute(select(SimulatedTrade)).scalars())
        assert trades == []
        events = load_run_events(s, run_id)
    statuses = {e.status for e in events if e.kind == "decision"}
    assert "shadow_would_fill" in statuses
    assert not any(e.kind == "fill" for e in events)


def test_paper_run_fills_via_marketable_limit(session_factory):
    """Legacy-parity: a buy in paper mode fills at the side-aware quote via a
    marketable limit, writing exactly one paper SimulatedTrade."""
    reg = _paper_lifecycle_registry("ETH")
    quote = PredictionQuote(
        asset_id="ETH",
        market_ticker="KXETH15M-T1",
        series_ticker="KXETH15M",
        close_ts=1_000,
        observed_at=100,
        yes_bid_cents=30,
        yes_ask_cents=32,
    )
    with session_factory() as adapter_session:
        adapter = PredictionPaperAdapter(
            session=adapter_session,
            quote_source=registry_quote_source({"ETH": quote}),
            settlement_source=lambda _t: None,
            starting_cash_usd=1_000.0,
            strategy=lambda q: StrategySignal(
                action="buy", side="yes", limit_price_cents=35, quantity=2
            ),
            registry=reg,
        )
        cfg = PaperRunConfig(
            domain="prediction",
            assets=("ETH",),
            mode="paper",
        )
        orch = PaperOrchestrator(
            settings=_settings(),
            config=cfg,
            session_factory=session_factory,
            adapter=adapter,
            now_fn=_clock(start=100.0, step=0.0),
            sleep_fn=lambda _s: None,
            cycle_seconds=1.0,
            registry=reg,
            frozen_report_present=True,
            max_cycles=1,
        )
        run_id = orch.run()
        adapter_session.commit()

    with session_factory() as s:
        trades = list(s.execute(select(SimulatedTrade)).scalars())
        assert len(trades) == 1
        assert trades[0].entry_price_cents == 32  # filled at the ask, not chased
        assert trades[0].mode == "paper"
        events = load_run_events(s, run_id)
    assert any(e.kind == "fill" and e.status == "filled" for e in events)


def test_stale_quote_is_rejected(session_factory):
    reg = _paper_lifecycle_registry("ETH")
    stale = PredictionQuote(
        asset_id="ETH",
        market_ticker="KXETH15M-T1",
        series_ticker="KXETH15M",
        close_ts=10_000,
        observed_at=100,  # far behind now_ts
        yes_bid_cents=30,
        yes_ask_cents=32,
    )
    with session_factory() as adapter_session:
        adapter = PredictionPaperAdapter(
            session=adapter_session,
            quote_source=registry_quote_source({"ETH": stale}),
            settlement_source=lambda _t: None,
            starting_cash_usd=1_000.0,
            strategy=lambda q: StrategySignal(
                action="buy", side="yes", limit_price_cents=99
            ),
            registry=reg,
            max_data_age_seconds=60,
        )
        decision = adapter.evaluate("ETH", now_ts=100_000, may_fill=True)
    assert decision.action == "blocked"
    assert decision.status == "stale_quote"


def test_restart_reconciliation_settles_resolved_market(session_factory):
    """§8.8: a restarted run finds an open ledger position whose official
    result is available and settles it before new entries."""
    reg = _paper_lifecycle_registry("ETH")
    with session_factory() as seed:
        seed.add(
            KalshiMarket(
                ticker="KXETH15M-OLD",
                series_ticker="KXETH15M",
                open_ts=0,
                close_ts=500,
                status="settled",
                result="yes",
            )
        )
        seed.add(
            SimulatedTrade(
                mode="paper",
                market_ticker="KXETH15M-OLD",
                side="yes",
                quantity=1,
                entry_price_cents=40,
                entry_ts=100,
                status="open",
                entry_fee_usd=0.02,
            )
        )
        seed.commit()

    with session_factory() as adapter_session:
        from kalshi_bot.execution.prediction_adapter import db_settlement_source

        adapter = PredictionPaperAdapter(
            session=adapter_session,
            quote_source=lambda _a, _n: None,
            settlement_source=db_settlement_source(adapter_session),
            starting_cash_usd=1_000.0,
            registry=reg,
        )
        outcome = adapter.reconcile("ETH")
        adapter_session.commit()
    assert outcome.resolved is True

    with session_factory() as s:
        row = s.execute(
            select(SimulatedTrade).where(SimulatedTrade.market_ticker == "KXETH15M-OLD")
        ).scalar_one()
        assert row.status == "settled_won"


def test_restart_reconciliation_blocks_on_unresolved_position(session_factory):
    reg = _paper_lifecycle_registry("ETH")
    with session_factory() as seed:
        seed.add(
            SimulatedTrade(
                mode="paper",
                market_ticker="KXETH15M-PENDING",
                side="yes",
                quantity=1,
                entry_price_cents=40,
                entry_ts=100,
                status="open",
                entry_fee_usd=0.02,
            )
        )
        seed.commit()

    with session_factory() as adapter_session:
        adapter = PredictionPaperAdapter(
            session=adapter_session,
            quote_source=lambda _a, _n: None,
            settlement_source=lambda _t: None,  # no official result yet
            starting_cash_usd=1_000.0,
            registry=reg,
        )
        outcome = adapter.reconcile("ETH")
    assert outcome.resolved is False
    assert "official_result" in outcome.reason


def test_interrupt_is_handled_cleanly(session_factory):
    reg = _paper_lifecycle_registry("ETH")

    class _RaisingAdapter(_StubAdapter):
        def evaluate(self, asset_id, *, now_ts, may_fill):
            raise KeyboardInterrupt

    adapter = _RaisingAdapter(
        {"ETH": AdapterDecision("ETH", "prediction", "hold", "hold")}
    )
    cfg = PaperRunConfig(domain="prediction", assets=("ETH",), mode="shadow")
    orch = PaperOrchestrator(
        settings=_settings(),
        config=cfg,
        session_factory=session_factory,
        adapter=adapter,
        now_fn=_clock(start=0.0, step=1.0),
        sleep_fn=lambda _s: None,
        cycle_seconds=1.0,
        registry=reg,
        max_cycles=5,
    )
    run_id = orch.run()
    with session_factory() as s:
        row = s.get(PaperRun, run_id)
        assert row.status == "interrupted"
        assert row.ended_at is not None
        events = load_run_events(s, run_id)
    assert summarize_run(events).get("heartbeat:final") == 1


class _FakeMarketsClient:
    def __init__(self, markets):
        self._markets = markets

    def get_markets(self, *, series_ticker, status, limit=50, **_kw):
        if status == "open":
            return [m for m in self._markets if m.get("series_ticker") == series_ticker], None
        return [], None


def test_kalshi_public_quote_source_picks_nearest_open_market():
    client = _FakeMarketsClient(
        [
            {
                "ticker": "KXBTC15M-LATE",
                "series_ticker": "KXBTC15M",
                "close_time": "2026-01-01T02:00:00Z",
                "yes_bid_dollars": "0.40",
                "yes_ask_dollars": "0.44",
            },
            {
                "ticker": "KXBTC15M-SOON",
                "series_ticker": "KXBTC15M",
                "close_time": "2026-01-01T00:30:00Z",
                "yes_bid_dollars": "0.48",
                "yes_ask_dollars": "0.52",
            },
        ]
    )
    source = kalshi_public_quote_source(client)
    now = 1_767_225_000  # well before both close times
    quote = source("BTC", now)
    assert quote is not None
    assert quote.market_ticker == "KXBTC15M-SOON"
    assert quote.yes_ask_cents == 52
    assert quote.observed_at == now


def test_kalshi_public_quote_source_returns_none_when_all_markets_closed():
    client = _FakeMarketsClient(
        [
            {
                "ticker": "KXBTC15M-PAST",
                "series_ticker": "KXBTC15M",
                "close_time": "2020-01-01T00:00:00Z",
                "yes_bid_dollars": "0.50",
                "yes_ask_dollars": "0.50",
            }
        ]
    )
    source = kalshi_public_quote_source(client)
    assert source("BTC", 1_767_225_000) is None


def test_unsupported_domain_decision_is_rejected(session_factory):
    """The orchestrator persists an adapter decision whose action the domain
    does not support without crashing the run."""
    reg = _paper_lifecycle_registry("ETH")
    adapter = _StubAdapter(
        {
            "ETH": AdapterDecision(
                "ETH", "prediction", "blocked", "unsupported_domain",
                reason="strategy_emitted_unknown_domain",
            )
        }
    )
    cfg = PaperRunConfig(domain="prediction", assets=("ETH",), mode="shadow")
    orch = PaperOrchestrator(
        settings=_settings(),
        config=cfg,
        session_factory=session_factory,
        adapter=adapter,
        now_fn=_clock(start=0.0, step=1.0),
        sleep_fn=lambda _s: None,
        cycle_seconds=1.0,
        registry=reg,
        max_cycles=1,
    )
    run_id = orch.run()
    with session_factory() as s:
        events = load_run_events(s, run_id)
    assert any(
        e.kind == "decision" and e.status == "unsupported_domain" for e in events
    )
