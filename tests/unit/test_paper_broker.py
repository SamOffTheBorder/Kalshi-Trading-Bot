"""PaperBroker: fills against live-polled quotes, persistence to
SimulatedTrade, and restart recovery (paper-trading-and-notify tasks.md
§2.1/§2.2).

Every order is required to be a limit order (operator decision: never a
quick/market buy) -- `place_order` rejects any `OrderRequest` without
`limit_price_cents`, and a limit worse than the current quote rejects with
`limit_exceeded` rather than chasing the market.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from kalshi_bot.execution.broker_protocol import MarketSnapshot, OrderRequest
from kalshi_bot.execution.paper_broker import PaperBroker
from kalshi_bot.storage.db import create_all_tables
from kalshi_bot.storage.models import SimulatedTrade


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    return sessionmaker(bind=engine)


def test_order_without_limit_price_is_rejected(session_factory):
    """The core "always limit, never quick-buy" guarantee."""
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1_000.0)
        broker.set_current_quote(
            MarketSnapshot(market_ticker="M1", ts=1, yes_bid_cents=40, yes_ask_cents=45)
        )
        result = _run(broker.place_order(OrderRequest(market_ticker="M1", side="yes", quantity=1)))
        assert result.status == "rejected"
        assert result.reject_reason == "limit_price_required"


def test_place_order_fills_at_worst_side_of_quote_within_limit(session_factory):
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1_000.0)
        broker.set_current_quote(
            MarketSnapshot(
                market_ticker="KXBTC15M-T1",
                ts=100,
                yes_bid_cents=48,
                yes_ask_cents=52,
            )
        )
        result = _run(
            broker.place_order(
                OrderRequest(
                    market_ticker="KXBTC15M-T1",
                    side="yes",
                    quantity=5,
                    limit_price_cents=52,
                )
            )
        )
        assert result.status == "filled"
        assert result.fill_price_cents == 52  # pays the ask, not the mid

        balance = _run(broker.get_account_balance())
        assert balance < 1_000.0  # stake + fee deducted


def test_buy_no_fills_at_100_minus_bid_within_limit(session_factory):
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1_000.0)
        broker.set_current_quote(
            MarketSnapshot(market_ticker="M1", ts=1, yes_bid_cents=40, yes_ask_cents=45)
        )
        result = _run(
            broker.place_order(
                OrderRequest(market_ticker="M1", side="no", quantity=2, limit_price_cents=60)
            )
        )
        assert result.status == "filled"
        assert result.fill_price_cents == 60  # 100 - 40


def test_limit_worse_than_quote_rejects_without_filling(session_factory):
    """The market moved against the intended price between decision and
    order -- the broker must refuse rather than chase (that's the whole
    point of always using a limit)."""
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1_000.0)
        broker.set_current_quote(
            MarketSnapshot(market_ticker="M1", ts=1, yes_bid_cents=40, yes_ask_cents=52)
        )
        result = _run(
            broker.place_order(
                OrderRequest(market_ticker="M1", side="yes", quantity=1, limit_price_cents=45)
            )
        )
        assert result.status == "rejected"
        assert result.reject_reason == "limit_exceeded"
        assert broker.open_position_tickers() == []


def test_limit_at_exactly_the_quote_fills(session_factory):
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1_000.0)
        broker.set_current_quote(
            MarketSnapshot(market_ticker="M1", ts=1, yes_bid_cents=40, yes_ask_cents=45)
        )
        result = _run(
            broker.place_order(
                OrderRequest(market_ticker="M1", side="yes", quantity=1, limit_price_cents=45)
            )
        )
        assert result.status == "filled"
        assert result.fill_price_cents == 45


def test_second_order_on_open_position_is_rejected(session_factory):
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1_000.0)
        broker.set_current_quote(
            MarketSnapshot(market_ticker="M1", ts=1, yes_bid_cents=40, yes_ask_cents=45)
        )
        _run(
            broker.place_order(
                OrderRequest(market_ticker="M1", side="yes", quantity=1, limit_price_cents=45)
            )
        )
        second = _run(
            broker.place_order(
                OrderRequest(market_ticker="M1", side="yes", quantity=1, limit_price_cents=45)
            )
        )
        assert second.status == "rejected"
        assert second.reject_reason == "position_already_open"


def test_no_quote_rejects(session_factory):
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1_000.0)
        result = _run(
            broker.place_order(
                OrderRequest(market_ticker="UNKNOWN", side="yes", quantity=1, limit_price_cents=50)
            )
        )
        assert result.status == "rejected"
        assert result.reject_reason == "no_market_data"


def test_insufficient_funds_rejects(session_factory):
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1.0)
        broker.set_current_quote(
            MarketSnapshot(market_ticker="M1", ts=1, yes_bid_cents=40, yes_ask_cents=45)
        )
        result = _run(
            broker.place_order(
                OrderRequest(market_ticker="M1", side="yes", quantity=100, limit_price_cents=45)
            )
        )
        assert result.status == "rejected"
        assert result.reject_reason == "insufficient_funds"


def test_maker_orders_unfilled(session_factory):
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1_000.0)
        broker.set_current_quote(
            MarketSnapshot(market_ticker="M1", ts=1, yes_bid_cents=40, yes_ask_cents=45)
        )
        result = _run(
            broker.place_order(
                OrderRequest(
                    market_ticker="M1",
                    side="yes",
                    quantity=1,
                    execution_style="maker",
                    limit_price_cents=40,
                )
            )
        )
        assert result.status == "rejected"
        assert result.reject_reason == "maker_unfilled_no_validated_model"


def test_fill_is_persisted_as_simulated_trade(session_factory):
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1_000.0)
        broker.set_current_quote(
            MarketSnapshot(market_ticker="M1", ts=1_000, yes_bid_cents=40, yes_ask_cents=45)
        )
        _run(
            broker.place_order(
                OrderRequest(market_ticker="M1", side="yes", quantity=3, limit_price_cents=45)
            )
        )
        session.commit()

        rows = list(session.execute(select(SimulatedTrade)).scalars())
        assert len(rows) == 1
        assert rows[0].mode == "paper"
        assert rows[0].status == "open"
        assert rows[0].quantity == 3
        assert rows[0].entry_price_cents == 45


def test_settle_market_wins_pays_out_and_closes(session_factory):
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1_000.0)
        broker.set_current_quote(
            MarketSnapshot(market_ticker="M1", ts=1, yes_bid_cents=40, yes_ask_cents=50)
        )
        _run(
            broker.place_order(
                OrderRequest(market_ticker="M1", side="yes", quantity=10, limit_price_cents=50)
            )
        )
        before = _run(broker.get_account_balance())

        broker.settle_market("M1", "yes", 2_000)
        session.commit()
        after = _run(broker.get_account_balance())

        assert after > before  # won: stake back + winnings
        assert broker.open_position_tickers() == []
        row = session.execute(select(SimulatedTrade)).scalar_one()
        assert row.status == "settled_won"
        assert row.net_pnl_usd is not None and row.net_pnl_usd > 0


def test_settle_market_loses_zeroes_position(session_factory):
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1_000.0)
        broker.set_current_quote(
            MarketSnapshot(market_ticker="M1", ts=1, yes_bid_cents=40, yes_ask_cents=50)
        )
        _run(
            broker.place_order(
                OrderRequest(market_ticker="M1", side="yes", quantity=10, limit_price_cents=50)
            )
        )
        broker.settle_market("M1", "no", 2_000)
        session.commit()

        row = session.execute(select(SimulatedTrade)).scalar_one()
        assert row.status == "settled_lost"
        assert row.net_pnl_usd is not None and row.net_pnl_usd < 0


def test_settle_unknown_ticker_is_a_noop(session_factory):
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1_000.0)
        broker.settle_market("NOPE", "yes", 1)  # must not raise


def test_restart_recovers_open_position_and_cash(session_factory):
    engine = session_factory().get_bind()
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1_000.0)
        broker.set_current_quote(
            MarketSnapshot(market_ticker="M1", ts=1, yes_bid_cents=40, yes_ask_cents=50)
        )
        _run(
            broker.place_order(
                OrderRequest(market_ticker="M1", side="yes", quantity=10, limit_price_cents=50)
            )
        )
        cash_after_fill = _run(broker.get_account_balance())
        session.commit()

    # Fresh broker instance over the same underlying data -- simulates a
    # process restart. New Session bound to the same in-memory engine.
    with sessionmaker(bind=engine)() as session2:
        restored = PaperBroker(session2, starting_cash_usd=1_000.0)
        assert restored.open_position_tickers() == ["M1"]
        restored_cash = _run(restored.get_account_balance())
        assert restored_cash == pytest.approx(cash_after_fill)


def test_restart_recovers_cash_from_settled_history(session_factory):
    engine = session_factory().get_bind()
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1_000.0)
        broker.set_current_quote(
            MarketSnapshot(market_ticker="M1", ts=1, yes_bid_cents=40, yes_ask_cents=50)
        )
        _run(
            broker.place_order(
                OrderRequest(market_ticker="M1", side="yes", quantity=10, limit_price_cents=50)
            )
        )
        broker.settle_market("M1", "yes", 2_000)
        final_cash = _run(broker.get_account_balance())
        session.commit()

    with sessionmaker(bind=engine)() as session2:
        restored = PaperBroker(session2, starting_cash_usd=1_000.0)
        assert restored.open_position_tickers() == []
        assert _run(restored.get_account_balance()) == pytest.approx(final_cash)


def test_get_market_snapshot_unknown_ticker_returns_empty(session_factory):
    with session_factory() as session:
        broker = PaperBroker(session, starting_cash_usd=1_000.0)
        snap = _run(broker.get_market_snapshot("UNKNOWN"))
        assert snap.yes_bid_cents is None
        assert snap.yes_ask_cents is None
