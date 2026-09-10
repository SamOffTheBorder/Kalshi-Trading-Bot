import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from kalshi_bot.execution.perp_paper import (
    PerpAccountState,
    PerpBracket,
    PerpOrder,
    PerpPaperAdapter,
    PerpPaperError,
    PerpQuote,
    bracket_exit,
    fill_perp_order,
    mark_to_market,
    realized_funding,
    validate_bracket,
)
from kalshi_bot.storage import PaperRun, PerpPaperEvent, PerpPaperPosition, create_all_tables


def test_perp_paper_fill_is_side_aware_and_fee_aware():
    quote = PerpQuote(99_900, 100_000, 10, 10, {"id": "q"})
    long = fill_perp_order(PerpOrder(0.01, 100, 0.01, 1, 0.001), quote, decision_ts=10)
    short = fill_perp_order(PerpOrder(-0.01, 100, 0.01, 1, 0.001), quote, decision_ts=10)
    assert long.fill_price == 100_000 and short.fill_price == 99_900
    assert long.fee_usd > 0


def test_perp_paper_rejects_unavailable_quote_and_calculates_margin_state():
    with pytest.raises(PerpPaperError, match="unavailable"):
        fill_perp_order(PerpOrder(1, 1, 1, 1, 0), PerpQuote(1, 2, 10, 11, {}), decision_ts=10)
    result = mark_to_market(PerpAccountState(100, 1, 100, 1), mark_price=110, liquidation_price=80)
    assert result.unrealized_pnl_usd == 10
    assert result.leverage == pytest.approx(1)
    assert (
        realized_funding(signed_quantity=1, multiplier=1, mark_price=100, funding_rate=0.01) == -1
    )


def test_perp_brackets_are_directional_and_fail_closed():
    bracket = PerpBracket(stop_loss=90, take_profit=120)
    validate_bracket(bracket, entry_price=100, signed_quantity=1)
    assert bracket_exit(bracket, signed_quantity=1, mark_price=90) == "stop_loss"
    with pytest.raises(PerpPaperError, match="long_bracket"):
        validate_bracket(PerpBracket(110, 120), entry_price=100, signed_quantity=1)


def test_persistence_adapter_records_fill_and_mark_events():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with Session(engine) as session:
        session.add(
            PaperRun(
                id="r",
                domain="perp",
                mode="paper",
                asset_ids=["BTC"],
                started_at=1,
                status="running",
                config_fingerprint="x",
            )
        )
        adapter = PerpPaperAdapter(
            session,
            paper_run_id="r",
            asset_id="BTC",
            market_ticker="KXBTCPERP",
            multiplier=1,
            minimum_size=0.01,
            tick_size=100,
            fee_rate=0.001,
        )
        position = adapter.open(
            0.01,
            PerpQuote(99_900, 100_000, 2, 2, {"source": "kalshi"}),
            decision_ts=2,
            bracket=PerpBracket(stop_loss=95_000, take_profit=110_000),
            collateral_usd=2_000,
        )
        adapter.record_mark(
            position, mark_price=100_100, observed_at=3, quote_reference={"source": "kalshi"}
        )
        session.commit()
        assert session.execute(select(PerpPaperPosition)).scalar_one().status == "open"
        assert len(session.execute(select(PerpPaperEvent)).scalars().all()) == 2
