"""Single schema of record.

Every persisted artifact — market candles, strategy evaluations (including
HOLDs), simulated trades, and backtest runs — lives in this one schema.
Column types are deliberately portable (no SQLite-only types) so the same
models move to Postgres unchanged.

Price convention: Kalshi contract prices are stored as integer cents (1-99),
matching the API. Dollar amounts (PnL, fees) are floats in USD. Candle
timestamps are integer epoch seconds, matching Kalshi's `end_period_ts`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Candle(Base):
    """One Kalshi market candlestick (contract prices, integer cents)."""

    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint(
            "market_ticker", "period_minutes", "end_period_ts", name="uq_candle_market_period_ts"
        ),
        Index("ix_candles_market_ts", "market_ticker", "end_period_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    series_ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    period_minutes: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 60, or 1440
    end_period_ts: Mapped[int] = mapped_column(Integer, nullable=False)  # epoch seconds

    # Trade-price OHLC; None when no trades occurred in the period.
    price_open: Mapped[int | None] = mapped_column(Integer)
    price_high: Mapped[int | None] = mapped_column(Integer)
    price_low: Mapped[int | None] = mapped_column(Integer)
    price_close: Mapped[int | None] = mapped_column(Integer)

    # Bid/ask closes — what pessimistic fill simulation needs.
    yes_bid_open: Mapped[int | None] = mapped_column(Integer)
    yes_bid_high: Mapped[int | None] = mapped_column(Integer)
    yes_bid_low: Mapped[int | None] = mapped_column(Integer)
    yes_bid_close: Mapped[int | None] = mapped_column(Integer)
    yes_ask_open: Mapped[int | None] = mapped_column(Integer)
    yes_ask_high: Mapped[int | None] = mapped_column(Integer)
    yes_ask_low: Mapped[int | None] = mapped_column(Integer)
    yes_ask_close: Mapped[int | None] = mapped_column(Integer)

    volume: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    open_interest: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class SpotCandle(Base):
    """Crypto spot kline (USD floats) from a CF Benchmarks constituent exchange.

    Feeds volatility estimation; kept separate from contract candles because
    the price domains differ (USD spot vs. cents-probability).
    """

    __tablename__ = "spot_candles"
    __table_args__ = (
        UniqueConstraint(
            "exchange", "symbol", "period_minutes", "open_ts", name="uq_spot_exchange_symbol_ts"
        ),
        Index("ix_spot_symbol_ts", "symbol", "open_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)  # "coinbase" | "kraken"
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)  # e.g. "BTC-USD"
    period_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    open_ts: Mapped[int] = mapped_column(Integer, nullable=False)  # epoch seconds

    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class BacktestRun(Base):
    """One backtest execution: parameters in, per-segment metrics out."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    data_start_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    data_end_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    # Boundary between train and test segments — out-of-sample split is
    # engine-enforced, not operator discipline (design decision 6).
    split_ts: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    metrics_train: Mapped[dict | None] = mapped_column(JSON)
    metrics_test: Mapped[dict | None] = mapped_column(JSON)


class SignalRecord(Base):
    """Every strategy evaluation — including HOLDs — with inputs and reasoning.

    The complete audit trail: if it was evaluated, it's here, whether or not
    a trade resulted.
    """

    __tablename__ = "signals"
    __table_args__ = (Index("ix_signals_run", "backtest_run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    evaluated_at_ts: Mapped[int] = mapped_column(Integer, nullable=False)  # market time
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # backtest|paper|live
    backtest_run_id: Mapped[int | None] = mapped_column(ForeignKey("backtest_runs.id"))

    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    market_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(8), nullable=False)  # BUY_YES|BUY_NO|HOLD

    market_yes_price: Mapped[int | None] = mapped_column(Integer)  # cents
    bs_probability: Mapped[float | None] = mapped_column(Float)
    mc_probability: Mapped[float | None] = mapped_column(Float)
    raw_edge: Mapped[float | None] = mapped_column(Float)
    fee_adjusted_edge: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    hold_reason: Mapped[str | None] = mapped_column(String(128))
    context: Mapped[str | None] = mapped_column(Text)  # JSON blob of full inputs


class SimulatedTrade(Base):
    """A simulated (backtest or paper) position lifecycle record."""

    __tablename__ = "simulated_trades"
    __table_args__ = (Index("ix_trades_run", "backtest_run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backtest_run_id: Mapped[int | None] = mapped_column(ForeignKey("backtest_runs.id"))
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"))
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # backtest|paper

    market_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # yes|no
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_ts: Mapped[int] = mapped_column(Integer, nullable=False)

    exit_price_cents: Mapped[int | None] = mapped_column(Integer)
    exit_ts: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    # open | settled_won | settled_lost | closed_early

    gross_pnl_usd: Mapped[float | None] = mapped_column(Float)
    fee_usd: Mapped[float | None] = mapped_column(Float)
    net_pnl_usd: Mapped[float | None] = mapped_column(Float)
