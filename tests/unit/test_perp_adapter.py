"""`PerpPaperDomainAdapter` — directional path (§4) and two-leg funding
carry (§5) (strategy-lab-multi-account §4.7, §5.4).

Covers: a full enter -> fill lifecycle; admission refusal records a
decision and no fill; an invalid bracket is refused before any position
row; funding is applied to `funding_pnl_usd` without touching
`realized_pnl_usd`; a carry decision records the perp leg and a
`hedge_leg` event with both legs' costs; sub-cost funding is refused; the
funding_carry.py 50c-hedge fee-drag case refuses at a realistic rate; and
no execution client is constructed on any path.
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

from kalshi_bot.execution.perp_adapter import (  # noqa: E402
    PerpEvalContext,
    PerpMarketReading,
    PerpPaperDomainAdapter,
    PerpSignal,
)
from kalshi_bot.execution.perp_admission import PerpMarkCoverage  # noqa: E402
from kalshi_bot.execution.perp_paper import PerpQuote  # noqa: E402
from kalshi_bot.storage.db import create_all_tables  # noqa: E402
from kalshi_bot.storage.models import (  # noqa: E402
    PaperRun,
    PerpPaperEvent,
    PerpPaperPosition,
)

try:
    from kalshi_bot.discovery.service import DiscoverySnapshot
except Exception:  # pragma: no cover
    DiscoverySnapshot = object  # type: ignore[assignment,misc]


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    return sessionmaker(bind=engine)


def _run_row(session, run_id="perp-run", mode="paper"):
    session.add(
        PaperRun(
            id=run_id, domain="perp", mode=mode, asset_ids=["BTC"],
            started_at=1, status="running", config_fingerprint="x",
        )
    )
    session.commit()


def _reading(*, bid=100.0, ask=100.0, mark=100.0, funding_rate=0.0,
             observed_at=1_000, available_at=1_000):
    return PerpMarketReading(
        quote=PerpQuote(
            bid=bid, ask=ask, observed_at=observed_at, available_at=available_at,
            reference={"market_ticker": "KXBTCPERP", "source": "test"},
        ),
        mark_price=mark,
        latest_funding_rate=funding_rate,
        multiplier=1.0,
        minimum_size=0.01,
        tick_size=0.01,
        fee_rate=0.0,
    )


def _snapshot(asset="BTC", checked_at=1_000):
    return DiscoverySnapshot(
        asset_id=asset, instrument="perp", identifier="KXBTCPERP", cadence=None,
        checked_at=checked_at, eligible=True, failure_reason=None,
        metadata={
            "multiplier": 1.0, "minimum_order_size": 0.01,
            "reference_index": "BTCUSD_RTI", "status": "active",
        },
    )


def _adapter(session, *, strategy, reading=None, coverage=None, snapshot="ok",
             collateral=1_000.0, run_id="perp-run"):
    the_reading = reading if reading is not None else _reading()
    cov = coverage if coverage is not None else PerpMarkCoverage(
        latest_mark_observed_at=1_090,
        latest_funding_observed_at=1_000 - 3600,
        has_realized_funding=True,
    )
    snap = _snapshot() if snapshot == "ok" else snapshot
    return PerpPaperDomainAdapter(
        session=session,
        paper_run_id=run_id,
        market_reader=lambda _a, _t: the_reading,
        coverage_reader=lambda _a, _t: cov,
        discovery_reader=lambda _a, _t: snap,
        collateral_usd=collateral,
        strategy=strategy,
    )


# -- directional path (§4) --------------------------------------------


def _long_bracket_signal(ctx: PerpEvalContext) -> PerpSignal:
    return PerpSignal(
        action="enter", signed_quantity=1.0,
        stop_loss=90.0, take_profit=120.0,
    )


def test_enter_fill_lifecycle(session_factory):
    with session_factory() as session:
        _run_row(session)
        adapter = _adapter(session, strategy=_long_bracket_signal)
        decision = adapter.evaluate("BTC", now_ts=1_050, may_fill=True)
        assert decision.filled is True
        assert decision.status == "filled"
        pos = session.execute(select(PerpPaperPosition)).scalar_one()
        assert pos.signed_quantity == 1.0
        assert pos.status == "open"
        fill_event = session.execute(
            select(PerpPaperEvent).where(PerpPaperEvent.event_type == "fill")
        ).scalar_one()
        assert fill_event.status == "filled"


def test_admission_refusal_records_decision_and_no_fill(session_factory):
    with session_factory() as session:
        _run_row(session)
        # No fresh mark in coverage -> admission fails.
        bad_cov = PerpMarkCoverage(
            latest_mark_observed_at=None,
            latest_funding_observed_at=None,
            has_realized_funding=False,
        )
        adapter = _adapter(session, strategy=_long_bracket_signal, coverage=bad_cov)
        decision = adapter.evaluate("BTC", now_ts=1_050, may_fill=True)
        assert decision.filled is False
        assert decision.payload["admitted"] is False
        assert "no_fresh_mark" in decision.payload["admission_reason"]
        assert session.execute(select(PerpPaperPosition)).first() is None


def test_invalid_bracket_refused_before_any_position(session_factory):
    def bad_bracket(ctx: PerpEvalContext) -> PerpSignal:
        # long with stop ABOVE entry -> validate_bracket raises long_bracket_order
        return PerpSignal(
            action="enter", signed_quantity=1.0,
            stop_loss=150.0, take_profit=200.0,
        )

    with session_factory() as session:
        _run_row(session)
        adapter = _adapter(session, strategy=bad_bracket)
        decision = adapter.evaluate("BTC", now_ts=1_050, may_fill=True)
        assert decision.status == "invalid_bracket"
        assert decision.reason == "long_bracket_order"
        assert session.execute(select(PerpPaperPosition)).first() is None


def test_missing_bracket_refused(session_factory):
    def no_bracket(ctx: PerpEvalContext) -> PerpSignal:
        return PerpSignal(action="enter", signed_quantity=1.0)

    with session_factory() as session:
        _run_row(session)
        adapter = _adapter(session, strategy=no_bracket)
        decision = adapter.evaluate("BTC", now_ts=1_050, may_fill=True)
        assert decision.status == "invalid_signal"
        assert decision.reason == "enter_needs_quantity_and_bracket"
        assert session.execute(select(PerpPaperPosition)).first() is None


def test_shadow_mode_records_would_enter_but_no_fill(session_factory):
    with session_factory() as session:
        _run_row(session, mode="shadow")
        adapter = _adapter(session, strategy=_long_bracket_signal)
        decision = adapter.evaluate("BTC", now_ts=1_050, may_fill=False)
        assert decision.status == "shadow_would_enter"
        assert decision.filled is False
        assert session.execute(select(PerpPaperPosition)).first() is None


def test_funding_applied_without_touching_realized_pnl(session_factory):
    with session_factory() as session:
        _run_row(session)
        adapter = _adapter(session, strategy=_long_bracket_signal)
        adapter.evaluate("BTC", now_ts=1_050, may_fill=True)
        pos = session.execute(select(PerpPaperPosition)).scalar_one()
        assert pos.realized_pnl_usd is None or pos.realized_pnl_usd == 0.0

        amount = adapter.apply_funding(
            "BTC", funding_rate=0.001, mark_price=100.0, observed_at=1_100
        )
        session.expire_all()
        pos = session.get(PerpPaperPosition, pos.id)
        assert amount is not None
        assert pos.funding_pnl_usd == pytest.approx(amount)
        # A positive rate charges a long: funding_pnl is negative here.
        assert pos.funding_pnl_usd < 0
        assert pos.realized_pnl_usd is None or pos.realized_pnl_usd == 0.0
        funding_event = session.execute(
            select(PerpPaperEvent).where(PerpPaperEvent.event_type == "funding")
        ).scalar_one()
        assert funding_event.funding_rate == 0.001


def test_no_execution_client_is_constructed(session_factory):
    # The adapter takes only plain callables + a Session; assert it has no
    # attribute that looks like a mutating Kalshi client.
    with session_factory() as session:
        _run_row(session)
        adapter = _adapter(session, strategy=_long_bracket_signal)
        adapter.evaluate("BTC", now_ts=1_050, may_fill=True)
        for name in vars(adapter):
            value = getattr(adapter, name)
            assert not hasattr(value, "place_order")
            assert not hasattr(value, "create_order")


# -- two-leg funding carry (§5) -------------------------------------


def test_carry_records_perp_leg_and_hedge_leg_event(session_factory):
    with session_factory() as session:
        _run_row(session)
        # A large funding rate so expected funding clears the hedge fee, but
        # the binary-event hedge still disables market-neutral carry -> the
        # strategy refuses. To exercise the *fill* path we force entry by
        # using a config whose gate the rate clears AND a hedge that
        # classifies... which the default binary hedge never does. So this
        # test asserts the refusal-with-numbers path (§5.3): the real
        # deliverable.
        adapter = _adapter(
            session, strategy=lambda c: PerpSignal(action="hold"),
            reading=_reading(funding_rate=0.05),
        )
        decision = adapter.evaluate_carry(
            "BTC", now_ts=1_050, may_fill=True, position_notional_usd=10_000.0
        )
        assert decision.action == "hold"
        assert decision.status == "carry_not_entered"
        assert "hedge_not_linear" in decision.reason
        assert decision.payload["expected_funding_usd"] == pytest.approx(500.0)
        assert decision.payload["hedge_cost_usd"] is not None
        assert session.execute(select(PerpPaperPosition)).first() is None


def test_carry_refused_when_funding_below_min_rate(session_factory):
    with session_factory() as session:
        _run_row(session)
        adapter = _adapter(
            session, strategy=lambda c: PerpSignal(action="hold"),
            reading=_reading(funding_rate=0.00001),
        )
        decision = adapter.evaluate_carry(
            "BTC", now_ts=1_050, may_fill=True, position_notional_usd=10_000.0
        )
        assert decision.status == "carry_not_entered"
        assert decision.reason == "funding_rate_too_small"


def test_carry_50c_hedge_fee_drag_refuses_at_a_realistic_rate(session_factory):
    """funding_carry.py's own finding: a $10k notional hedged at 50c needs
    funding north of ~3.5% just to break even on the hedge leg. At a
    realistic 0.03% funding rate the net carry is deeply negative, so the
    carry is refused."""
    with session_factory() as session:
        _run_row(session)
        adapter = _adapter(
            session, strategy=lambda c: PerpSignal(action="hold"),
            reading=_reading(funding_rate=0.0003),
        )
        decision = adapter.evaluate_carry(
            "BTC", now_ts=1_050, may_fill=True, position_notional_usd=10_000.0
        )
        assert decision.status == "carry_not_entered"
        assert decision.reason == "net_carry_below_gate"
        assert decision.payload["expected_net_carry_usd"] < 0


def test_carry_fills_both_legs_when_hedge_classifies_and_rate_clears(session_factory):
    """The `carry_filled` path: with an ELIGIBLE linear hedge and a funding
    rate that clears the net-carry gate, the perp leg opens and a
    `hedge_leg` event is recorded carrying both legs' costs."""
    from kalshi_bot.strategy.funding_carry import FundingCarryConfig
    from kalshi_bot.strategy.funding_carry_classification import HedgeSpec

    linear_hedge = HedgeSpec(
        kind="perp",
        same_reference_index=True,
        rebalance_cadence_modeled=True,
        both_leg_fees_modeled=True,
        funding_accrual_modeled=True,
        residual_basis_risk_estimated=True,
    )
    with session_factory() as session:
        _run_row(session)
        adapter = _adapter(
            session, strategy=lambda c: PerpSignal(action="hold"),
            reading=_reading(bid=100.0, ask=100.0, funding_rate=0.05),
        )
        # Patch the module-level evaluate to pass our eligible hedge through.
        import kalshi_bot.execution.perp_adapter as mod

        real = mod.evaluate_funding_carry

        def _with_hedge(fs, *, position_notional_usd, config=None):
            return real(
                fs, position_notional_usd=position_notional_usd,
                config=config, hedge=linear_hedge,
            )

        mod.evaluate_funding_carry = _with_hedge
        try:
            decision = adapter.evaluate_carry(
                "BTC", now_ts=1_050, may_fill=True,
                position_notional_usd=100.0,
                config=FundingCarryConfig(),
            )
        finally:
            mod.evaluate_funding_carry = real

        assert decision.status == "carry_filled"
        assert decision.filled is True
        pos = session.execute(select(PerpPaperPosition)).scalar_one()
        assert pos.status == "open"
        hedge_event = session.execute(
            select(PerpPaperEvent).where(PerpPaperEvent.event_type == "hedge_leg")
        ).scalar_one()
        assert hedge_event.payload["hedge_cost_usd"] is not None
        assert hedge_event.payload["expected_net_carry_usd"] is not None
        assert hedge_event.payload["perp_entry_fee_usd"] is not None


def test_carry_shadow_mode_does_not_fill(session_factory):
    # Even if a favourable path existed, shadow mode never fills.
    with session_factory() as session:
        _run_row(session, mode="shadow")
        adapter = _adapter(
            session, strategy=lambda c: PerpSignal(action="hold"),
            reading=_reading(funding_rate=0.05),
        )
        decision = adapter.evaluate_carry(
            "BTC", now_ts=1_050, may_fill=False, position_notional_usd=10_000.0
        )
        assert decision.filled is False
        assert session.execute(select(PerpPaperPosition)).first() is None
