"""Perpetual bracket / leverage / liquidation / gap / restart safety
(multi-venue-paper-trading §9.5-9.7, §9.9).

Covers: long/short realized PnL sign, funding sign, tick + minimum size,
stale / one-sided quote, margin (collateral) rejection, leverage cap and the
3x ceiling clamp, bracket-required + directional bracket failure, mark-gap
stop fills, liquidation forced close, emergency-halt close, restart
reconciliation blocking new entries, perp admission reasons, and the
binary/perp ledger staying separate.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from kalshi_bot.discovery.service import DiscoverySnapshot
from kalshi_bot.execution.perp_admission import (
    PerpMarkCoverage,
    evaluate_perp_admission,
)
from kalshi_bot.execution.perp_paper import (
    ABSOLUTE_MAX_LEVERAGE,
    PerpBracket,
    PerpOrder,
    PerpPaperAdapter,
    PerpPaperError,
    PerpQuote,
    check_entry_leverage,
    close_perp_position,
    evaluate_perp_step,
    fill_perp_order,
    liquidation_price,
    realized_funding,
)
from kalshi_bot.storage import (
    PaperRun,
    PerpPaperEvent,
    PerpPaperPosition,
    SimulatedTrade,
    create_all_tables,
)


def _run(session: Session, run_id="r") -> None:
    session.add(
        PaperRun(
            id=run_id,
            domain="perp",
            mode="paper",
            asset_ids=["BTC"],
            started_at=1,
            status="running",
            config_fingerprint="x",
        )
    )


def _adapter(session, **kw) -> PerpPaperAdapter:
    defaults = dict(
        paper_run_id="r",
        asset_id="BTC",
        market_ticker="KXBTCPERP",
        multiplier=1.0,
        minimum_size=0.01,
        tick_size=100.0,
        fee_rate=0.0004,
        collateral_usd=5_000.0,
        max_leverage=2.0,
    )
    defaults.update(kw)
    return PerpPaperAdapter(session, **defaults)


# --------------------------------------------------------------------------
# Pure calc: PnL / funding sign, tick + size, quotes
# --------------------------------------------------------------------------


def test_long_and_short_realized_pnl_have_opposite_sign():
    up = close_perp_position(
        signed_quantity=1, entry_price=100, multiplier=1, fee_rate=0,
        entry_fee_usd=0, funding_pnl_usd=0, exit_price=110, reason="take_profit",
    )
    down = close_perp_position(
        signed_quantity=-1, entry_price=100, multiplier=1, fee_rate=0,
        entry_fee_usd=0, funding_pnl_usd=0, exit_price=110, reason="stop_loss",
    )
    assert up.realized_pnl_usd == 10
    assert down.realized_pnl_usd == -10


def test_funding_sign_charges_long_credits_short():
    long_f = realized_funding(signed_quantity=1, multiplier=1, mark_price=100, funding_rate=0.01)
    short_f = realized_funding(signed_quantity=-1, multiplier=1, mark_price=100, funding_rate=0.01)
    assert long_f == -1
    assert short_f == 1


def test_fill_enforces_minimum_size_and_tick():
    good = PerpQuote(bid=99_900, ask=100_000, observed_at=5, available_at=5, reference={})
    with pytest.raises(PerpPaperError, match="minimum_size"):
        fill_perp_order(PerpOrder(0.001, 100, 0.01, 1, 0), good, decision_ts=10)
    off_tick = PerpQuote(bid=99_950, ask=100_050, observed_at=5, available_at=5, reference={})
    with pytest.raises(PerpPaperError, match="off_tick"):
        fill_perp_order(PerpOrder(0.02, 100, 0.01, 1, 0), off_tick, decision_ts=10)


def test_fill_rejects_stale_and_one_sided_quotes():
    stale = PerpQuote(bid=1, ask=2, observed_at=99, available_at=99, reference={})
    with pytest.raises(PerpPaperError, match="unavailable"):
        fill_perp_order(PerpOrder(1, 1, 1, 1, 0), stale, decision_ts=10)
    one_sided = PerpQuote(bid=None, ask=100, observed_at=5, available_at=5, reference={})
    with pytest.raises(PerpPaperError, match="one_sided"):
        fill_perp_order(PerpOrder(-1, 1, 1, 1, 0), one_sided, decision_ts=10)


# --------------------------------------------------------------------------
# Leverage / liquidation
# --------------------------------------------------------------------------


def test_leverage_cap_and_absolute_ceiling_clamp():
    # 2x cap: 3 contracts * 100 price / 100 collateral = 3x -> rejected.
    v = check_entry_leverage(
        signed_quantity=3, multiplier=1, price=100, collateral_usd=100, max_leverage=2.0
    )
    assert not v.ok and v.reason == "leverage_or_minimum_size"
    # A caller asking for 10x is clamped to the 3x absolute ceiling.
    v2 = check_entry_leverage(
        signed_quantity=4, multiplier=1, price=100, collateral_usd=100, max_leverage=10.0
    )
    assert not v2.ok
    v3 = check_entry_leverage(
        signed_quantity=ABSOLUTE_MAX_LEVERAGE, multiplier=1, price=100,
        collateral_usd=100, max_leverage=10.0,
    )
    assert v3.ok


def test_liquidation_price_below_entry_for_long_above_for_short():
    long_liq = liquidation_price(
        signed_quantity=1, entry_price=100, multiplier=1, collateral_usd=20
    )
    short_liq = liquidation_price(
        signed_quantity=-1, entry_price=100, multiplier=1, collateral_usd=20
    )
    assert long_liq is not None and long_liq < 100
    assert short_liq is not None and short_liq > 100


# --------------------------------------------------------------------------
# Adapter: bracket required, margin rejection, gap, liquidation, halt
# --------------------------------------------------------------------------


def test_open_requires_a_representable_bracket():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with Session(engine) as s:
        _run(s)
        adapter = _adapter(s)
        q = PerpQuote(bid=99_900, ask=100_000, observed_at=2, available_at=2, reference={})
        with pytest.raises(PerpPaperError, match="bracket_required"):
            adapter.open(0.01, q, decision_ts=2)
        with pytest.raises(PerpPaperError, match="long_bracket"):
            adapter.open(
                0.01, q, decision_ts=2,
                bracket=PerpBracket(stop_loss=101_000, take_profit=110_000),
            )


def test_open_rejected_when_collateral_too_small():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with Session(engine) as s:
        _run(s)
        adapter = _adapter(s, collateral_usd=100.0)  # 0.05 * 100_000 = 5_000 notional -> 50x
        q = PerpQuote(bid=99_900, ask=100_000, observed_at=2, available_at=2, reference={})
        with pytest.raises(PerpPaperError, match="leverage_or_minimum_size"):
            adapter.open(
                0.05, q, decision_ts=2,
                bracket=PerpBracket(stop_loss=95_000, take_profit=110_000),
                collateral_usd=100.0,
            )


def test_step_forces_liquidation_before_bracket():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with Session(engine) as s:
        _run(s)
        # 0.1 * 100_000 = 10_000 notional; 6_000 collateral -> 1.67x, within 2x.
        adapter = _adapter(s, collateral_usd=6_000.0)
        q = PerpQuote(bid=99_900, ask=100_000, observed_at=2, available_at=2, reference={})
        pos = adapter.open(
            0.1, q, decision_ts=2,
            bracket=PerpBracket(stop_loss=80_000, take_profit=130_000),
            collateral_usd=6_000.0,
        )
        # A crash well past the liquidation estimate (~ -60% equity wipe).
        decision = adapter.step(
            pos,
            mark_price=30_000,
            prev_mark_price=100_000,
            observed_at=9,
            quote_reference={"source": "kalshi"},
            bracket=PerpBracket(stop_loss=80_000, take_profit=130_000),
            collateral_usd=6_000.0,
        )
        s.commit()
        assert decision.reason == "liquidation"
        assert s.get(PerpPaperPosition, pos.id).status == "liquidated"
        kinds = {e.event_type for e in s.execute(select(PerpPaperEvent)).scalars()}
        assert "liquidation" in kinds


def test_step_gap_through_stop_fills_at_worse_mark():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with Session(engine) as s:
        _run(s)
        adapter = _adapter(s, collateral_usd=50_000.0)
        q = PerpQuote(bid=99_900, ask=100_000, observed_at=2, available_at=2, reference={})
        bracket = PerpBracket(stop_loss=95_000, take_profit=120_000)
        pos = adapter.open(0.1, q, decision_ts=2, bracket=bracket, collateral_usd=50_000.0)
        decision = adapter.step(
            pos,
            mark_price=90_000,  # gapped straight through the 95_000 stop
            prev_mark_price=100_000,
            observed_at=9,
            quote_reference={},
            bracket=bracket,
            collateral_usd=50_000.0,
        )
        s.commit()
        assert decision.reason == "stop_loss_gap"
        assert decision.exit_price == 90_000
        assert s.get(PerpPaperPosition, pos.id).status == "closed"


def test_step_emergency_halt_closes_position():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with Session(engine) as s:
        _run(s)
        adapter = _adapter(s, collateral_usd=50_000.0)
        q = PerpQuote(bid=99_900, ask=100_000, observed_at=2, available_at=2, reference={})
        bracket = PerpBracket(stop_loss=95_000, take_profit=120_000)
        pos = adapter.open(0.1, q, decision_ts=2, bracket=bracket, collateral_usd=50_000.0)
        decision = adapter.step(
            pos,
            mark_price=100_500,
            prev_mark_price=100_000,
            observed_at=9,
            quote_reference={},
            bracket=bracket,
            collateral_usd=50_000.0,
            halted=True,
        )
        s.commit()
        assert decision.reason == "emergency_halt"
        assert s.get(PerpPaperPosition, pos.id).status == "closed"


def test_step_missing_mark_triggers_reconciliation_not_a_fake_close():
    decision = evaluate_perp_step(
        signed_quantity=1,
        entry_price=100,
        bracket=PerpBracket(90, 120),
        mark_price=None,
        prev_mark_price=100,
        liq_price=80,
        halted=False,
    )
    assert decision.action == "hold"
    assert decision.reason == "mark_unavailable_reconcile"


# --------------------------------------------------------------------------
# Restart reconciliation (§9.7)
# --------------------------------------------------------------------------


def test_restart_blocks_new_entries_without_a_fresh_mark():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with Session(engine) as s:
        _run(s)
        adapter = _adapter(s, collateral_usd=50_000.0)
        q = PerpQuote(bid=99_900, ask=100_000, observed_at=2, available_at=2, reference={})
        adapter.open(
            0.1, q, decision_ts=2,
            bracket=PerpBracket(95_000, 120_000), collateral_usd=50_000.0,
        )
        s.commit()

    with Session(engine) as s:
        adapter = _adapter(s, collateral_usd=50_000.0)
        blocked = adapter.reconcile_open_positions(
            fresh_mark=None, mark_observed_at=None, now_ts=10_000
        )
        assert blocked.reconciled is False
        assert blocked.reason == "no_fresh_mark_on_restart"

        ok = adapter.reconcile_open_positions(
            fresh_mark=100_100, mark_observed_at=9_990, now_ts=10_000
        )
        assert ok.reconciled is True
        s.commit()
        recon_events = [
            e for e in s.execute(select(PerpPaperEvent)).scalars()
            if e.event_type == "reconciliation"
        ]
        assert {e.status for e in recon_events} == {"reconciliation_required", "reconciled"}


def test_no_open_positions_reconciles_trivially():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with Session(engine) as s:
        _run(s)
        adapter = _adapter(s)
        out = adapter.reconcile_open_positions(
            fresh_mark=None, mark_observed_at=None, now_ts=1
        )
        assert out.reconciled is True and out.reason == "no_open_positions"


# --------------------------------------------------------------------------
# Admission (§9.6)
# --------------------------------------------------------------------------


def _perp_snapshot(asset="BTC", checked_at=1_000, **meta):
    base = {
        "multiplier": 1.0,
        "minimum_order_size": 0.01,
        "reference_index": "BTCUSD_RTI",
        "funding_available": True,
        "status": "active",
    }
    base.update(meta)
    return DiscoverySnapshot(
        asset_id=asset,
        instrument="perp",
        identifier="KXBTCPERP",
        cadence=None,
        checked_at=checked_at,
        eligible=True,
        failure_reason=None,
        metadata=base,
    )


def test_admission_happy_path_admits_for_paper():
    v = evaluate_perp_admission(
        asset_id="BTC",
        now_ts=1_100,
        discovery=_perp_snapshot(checked_at=1_000),
        coverage=PerpMarkCoverage(
            latest_mark_observed_at=1_090,
            latest_funding_observed_at=1_000 - 3600,
            has_realized_funding=True,
        ),
        frozen_report_present=True,
        paper_mode=True,
    )
    assert v.admitted and v.may_fill and v.reason == "admitted_for_paper"


def test_admission_blocks_unconfigured_asset():
    v = evaluate_perp_admission(
        asset_id="AAVE",
        now_ts=1_100,
        discovery=_perp_snapshot(asset="AAVE"),
        coverage=PerpMarkCoverage(1_090, 1_000, True),
        frozen_report_present=True,
        paper_mode=True,
    )
    assert not v.admitted and v.reason == "asset_not_active"


def test_admission_blocks_on_stale_or_missing_funding():
    stale_funding = evaluate_perp_admission(
        asset_id="SOL",
        now_ts=1_000_000,
        discovery=_perp_snapshot(asset="SOL", checked_at=999_500, reference_index="SOLUSD_RTI"),
        coverage=PerpMarkCoverage(
            latest_mark_observed_at=999_950,
            latest_funding_observed_at=1,
            has_realized_funding=True,
        ),
        frozen_report_present=True,
        paper_mode=True,
    )
    assert not stale_funding.admitted and stale_funding.reason == "stale_realized_funding"

    no_funding = evaluate_perp_admission(
        asset_id="SOL",
        now_ts=1_100,
        discovery=_perp_snapshot(asset="SOL", checked_at=1_000, reference_index="SOLUSD_RTI"),
        coverage=PerpMarkCoverage(1_090, None, False),
        frozen_report_present=True,
        paper_mode=True,
    )
    assert not no_funding.admitted and no_funding.reason == "no_realized_funding_coverage"


def test_admission_decision_only_without_report_or_paper_mode():
    common = dict(
        asset_id="ETH",
        now_ts=1_100,
        discovery=_perp_snapshot(asset="ETH", checked_at=1_000, reference_index="ETHUSD_RTI"),
        coverage=PerpMarkCoverage(1_090, 1_000 - 3600, True),
    )
    no_report = evaluate_perp_admission(**common, frozen_report_present=False, paper_mode=True)
    assert no_report.admitted and not no_report.may_fill
    assert no_report.reason == "admitted_for_decisions_only"

    shadow = evaluate_perp_admission(**common, frozen_report_present=True, paper_mode=False)
    assert shadow.admitted and not shadow.may_fill
    assert shadow.reason == "shadow_mode_no_paper_fill"


# --------------------------------------------------------------------------
# Ledger separation (§9.9)
# --------------------------------------------------------------------------


def test_perp_close_never_writes_a_binary_simulated_trade():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with Session(engine) as s:
        _run(s)
        adapter = _adapter(s, collateral_usd=50_000.0)
        q = PerpQuote(bid=99_900, ask=100_000, observed_at=2, available_at=2, reference={})
        bracket = PerpBracket(95_000, 120_000)
        pos = adapter.open(0.1, q, decision_ts=2, bracket=bracket, collateral_usd=50_000.0)
        adapter.close(
            pos, exit_price=110_000, reason="take_profit", observed_at=9, quote_reference={}
        )
        s.commit()
        assert s.execute(select(SimulatedTrade)).first() is None
        assert s.get(PerpPaperPosition, pos.id).status == "closed"
