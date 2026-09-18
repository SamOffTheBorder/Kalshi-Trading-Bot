"""End-to-end exercise of the paper trading loop (`run()`) against fakes --
no real Kalshi network calls. Covers: signals persisted every cycle
(including HOLDs), and a BUY decision routed through PaperBroker as a limit
order.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from kalshi_bot.config.settings import Settings  # noqa: E402
from kalshi_bot.data.brti.poll import BRTIReadingRaw  # noqa: E402
from kalshi_bot.storage.db import create_all_tables  # noqa: E402
from kalshi_bot.storage.models import SignalRecord, SimulatedTrade  # noqa: E402
from kalshi_bot.strategy.base import Action, Decision  # noqa: E402


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "run_paper_trading", REPO_ROOT / "scripts" / "run_paper_trading.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rpt = _load_module()


class _FakeBRTISource:
    """Deterministic BRTI ticks: starts at 100_000, no drift, tiny noise so
    the strategy sees a usable window without a real network call."""

    def __init__(self, values: list[float], start_ts: int) -> None:
        self._values = iter(values)
        self._ts = start_ts

    def fetch(self) -> BRTIReadingRaw | None:
        try:
            v = next(self._values)
        except StopIteration:
            return None
        reading = BRTIReadingRaw(observed_at=self._ts, value=v, source="fake:test")
        self._ts += 1
        return reading

    def close(self) -> None:
        pass


class _FakePublicClient:
    """Stands in for KalshiPublicClient -- never opens a real connection."""

    def __init__(self, markets: list[dict], settled: list[dict] | None = None) -> None:
        self._markets = markets
        self._settled = settled or []

    def get_markets(self, *, series_ticker, status, limit=1000, **_kwargs):
        if status == "open":
            return self._markets, None
        if status == "settled":
            return self._settled, None
        return [], None

    def close(self) -> None:
        pass


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def settings():
    return Settings(kalshi_key_id=None, db_path="unused.db", bankroll_total_usd=1_000.0)


def _market(ticker: str, close_iso: str, yes_bid: str, yes_ask: str) -> dict:
    return {
        "ticker": ticker,
        "series_ticker": "KXBTC15M",
        "strike_type": "greater_or_equal",
        "floor_strike": 100_000.0,
        "cap_strike": None,
        "close_time": close_iso,
        "yes_bid_dollars": yes_bid,
        "yes_ask_dollars": yes_ask,
    }


def test_loop_records_hold_signals_when_no_edge(session_factory, settings, monkeypatch):
    """With a flat BRTI series and a wide spread, the strategy should HOLD
    every cycle -- and every HOLD must still be persisted (audit trail)."""
    market = _market("KXBTC15M-T1", "2026-01-01T00:15:00Z", "0.40", "0.60")
    fake_client = _FakePublicClient([market])
    fake_brti = _FakeBRTISource([100_000.0] * 50, start_ts=1_735_689_000)

    monkeypatch.setattr(rpt, "KalshiPublicClient", lambda: fake_client)
    monkeypatch.setattr(rpt, "_build_brti_source", lambda _settings: fake_brti)

    ticks = iter([1_735_689_000.0, 1_735_689_005.0, 1_735_689_010.5])

    def fake_now():
        try:
            return next(ticks)
        except StopIteration:
            return 1_735_689_100.0

    with session_factory() as session:
        rpt.run(
            settings=settings,
            session=session,
            duration_s=10.0,
            market_poll_s=1.0,
            brti_poll_s=1.0,
            now_fn=fake_now,
            sleep_fn=lambda _s: None,
        )
        session.commit()

        signal_count = session.execute(select(func.count(SignalRecord.id))).scalar_one()
        assert signal_count >= 1
        actions = {row[0] for row in session.execute(select(SignalRecord.action)).all()}
        assert actions == {"HOLD"}  # wide spread, no edge should ever clear


class _FixedBuyStrategy:
    """Forces a deterministic BUY_YES every cycle -- exercises the loop's
    order-construction path without depending on SettlementProbStrategy's
    internal timing/edge gates (which a hand-built fixture would otherwise
    have to reverse-engineer to trigger reliably)."""

    name = "fixed_buy_test_double"

    def __init__(self, entry_price_cents: int) -> None:
        self._entry_price_cents = entry_price_cents

    def evaluate(self, context) -> Decision:
        return Decision(
            action=Action.BUY_YES,
            market_ticker=context.market_ticker,
            strategy_name=self.name,
            fair_probability=0.9,
            confidence=0.8,
            fee_adjusted_edge=0.5,
            entry_price_cents=self._entry_price_cents,
            min_entry_price_cents=self._entry_price_cents - 2,
            max_entry_price_cents=self._entry_price_cents + 2,
        )


def test_loop_always_places_orders_as_limit_orders(session_factory, settings, monkeypatch):
    """Regression guard for the "always limit order, never quick-buy"
    requirement: the loop must attach `limit_price_cents` equal to the
    decision's own priced entry -- PaperBroker structurally rejects any
    order missing one, so a fill proves the loop actually built the order
    that way rather than relying on the broker's default."""
    market = _market("KXBTC15M-T2", "2026-01-01T00:15:00Z", "0.30", "0.32")
    fake_client = _FakePublicClient([market])
    fake_brti = _FakeBRTISource([100_000.0] * 50, start_ts=1_735_688_600)

    monkeypatch.setattr(rpt, "KalshiPublicClient", lambda: fake_client)
    monkeypatch.setattr(rpt, "_build_brti_source", lambda _settings: fake_brti)
    monkeypatch.setattr(
        rpt, "SettlementProbStrategy", lambda: _FixedBuyStrategy(entry_price_cents=32)
    )

    ticks = iter([1_735_689_000.0, 1_735_689_005.0, 1_735_689_010.5])

    def fake_now():
        try:
            return next(ticks)
        except StopIteration:
            return 1_735_689_100.0

    with session_factory() as session:
        rpt.run(
            settings=settings,
            session=session,
            duration_s=10.0,
            market_poll_s=1.0,
            brti_poll_s=1.0,
            now_fn=fake_now,
            sleep_fn=lambda _s: None,
        )
        session.commit()

        trades = list(session.execute(select(SimulatedTrade)).scalars())
        assert len(trades) == 1  # entry throttle/position-already-open cap further fills
        trade = trades[0]
        # Filled at the ask (32c), matching the forced decision's own priced
        # entry -- not an unconstrained/worse fill, because PaperBroker
        # would have rejected an order with no limit at all.
        assert trade.entry_price_cents == 32
        assert trade.mode == "paper"
        assert trade.side == "yes"


# EmergencyControl itself (drawdown/daily-loss/consecutive-loss composition,
# ControlPanel wiring, resume semantics) is covered exhaustively in
# tests/unit/test_emergency_control.py -- not duplicated here.
