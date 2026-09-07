"""Single schema of record.

Every persisted artifact — market candles, strategy evaluations (including
HOLDs), simulated trades, and backtest runs — lives in this one schema.
Column types are deliberately portable (no SQLite-only types) so the same
models move to Postgres unchanged.

Legacy price columns remain integer cents for existing backtests. New writes
also retain the exact exchange dollar strings in nullable `*_dollars` columns;
historical rows are never rewritten.
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
    observed_at: Mapped[int | None] = mapped_column(Integer)
    available_at: Mapped[int | None] = mapped_column(Integer)
    capture_session_id: Mapped[str | None] = mapped_column(String(64))
    source_endpoint: Mapped[str | None] = mapped_column(String(256))
    fetched_at: Mapped[int | None] = mapped_column(Integer)
    provenance: Mapped[dict | None] = mapped_column(JSON)

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

    # Exact API values. Kept as strings to avoid Decimal/float conversion loss.
    price_open_dollars: Mapped[str | None] = mapped_column(String(32))
    price_high_dollars: Mapped[str | None] = mapped_column(String(32))
    price_low_dollars: Mapped[str | None] = mapped_column(String(32))
    price_close_dollars: Mapped[str | None] = mapped_column(String(32))
    yes_bid_open_dollars: Mapped[str | None] = mapped_column(String(32))
    yes_bid_high_dollars: Mapped[str | None] = mapped_column(String(32))
    yes_bid_low_dollars: Mapped[str | None] = mapped_column(String(32))
    yes_bid_close_dollars: Mapped[str | None] = mapped_column(String(32))
    yes_ask_open_dollars: Mapped[str | None] = mapped_column(String(32))
    yes_ask_high_dollars: Mapped[str | None] = mapped_column(String(32))
    yes_ask_low_dollars: Mapped[str | None] = mapped_column(String(32))
    yes_ask_close_dollars: Mapped[str | None] = mapped_column(String(32))
    volume_fp: Mapped[str | None] = mapped_column(String(32))
    open_interest_fp: Mapped[str | None] = mapped_column(String(32))

    volume: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    open_interest: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class KalshiMarket(Base):
    """Market metadata needed to settle backtest positions: strike + result.

    Candles alone can't settle a simulated position — the strike structure and
    official result live here, captured when historical data is fetched.
    """

    __tablename__ = "kalshi_markets"
    __table_args__ = (Index("ix_markets_series_close", "series_ticker", "close_ts"),)

    ticker: Mapped[str] = mapped_column(String(64), primary_key=True)
    series_ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    event_ticker: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(256))

    strike_type: Mapped[str | None] = mapped_column(String(16))  # greater|less|between|...
    floor_strike: Mapped[float | None] = mapped_column(Float)
    cap_strike: Mapped[float | None] = mapped_column(Float)
    floor_strike_exact: Mapped[str | None] = mapped_column(String(64))
    cap_strike_exact: Mapped[str | None] = mapped_column(String(64))

    open_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    close_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # settled|closed|active
    result: Mapped[str | None] = mapped_column(String(8))  # yes|no|None until settled
    observed_at: Mapped[int | None] = mapped_column(Integer)
    available_at: Mapped[int | None] = mapped_column(Integer)
    capture_session_id: Mapped[str | None] = mapped_column(String(64))
    source_endpoint: Mapped[str | None] = mapped_column(String(256))
    fetched_at: Mapped[int | None] = mapped_column(Integer)
    provenance: Mapped[dict | None] = mapped_column(JSON)


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
    observed_at: Mapped[int | None] = mapped_column(Integer)
    available_at: Mapped[int | None] = mapped_column(Integer)
    capture_session_id: Mapped[str | None] = mapped_column(String(64))
    provenance: Mapped[dict | None] = mapped_column(JSON)


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
    evidence_class: Mapped[str] = mapped_column(String(16), default="diagnostic", nullable=False)
    provenance: Mapped[dict | None] = mapped_column(JSON)
    fee_config_version: Mapped[str | None] = mapped_column(String(64))
    resolution_config_version: Mapped[str | None] = mapped_column(String(64))


class OrderBookSnapshot(Base):
    """A point-in-time public L2 snapshot; availability is when it was received."""

    __tablename__ = "order_book_snapshots"
    __table_args__ = (Index("ix_l2_ticker_available", "market_ticker", "available_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)
    bids: Mapped[list | dict] = mapped_column(JSON, nullable=False)
    asks: Mapped[list | dict] = mapped_column(JSON, nullable=False)
    capture_session_id: Mapped[str | None] = mapped_column(String(64))
    source_endpoint: Mapped[str | None] = mapped_column(String(256))
    fetched_at: Mapped[int | None] = mapped_column(Integer)
    provenance: Mapped[dict | None] = mapped_column(JSON)


class PublicTrade(Base):
    """A public market trade with exchange event time and local availability."""

    __tablename__ = "public_trades"
    __table_args__ = (Index("ix_public_trades_ticker_available", "market_ticker", "available_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)
    price_dollars: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity_fp: Mapped[str] = mapped_column(String(32), nullable=False)
    taker_side: Mapped[str | None] = mapped_column(String(8))
    trade_id: Mapped[str | None] = mapped_column(String(128))
    capture_session_id: Mapped[str | None] = mapped_column(String(64))
    source_endpoint: Mapped[str | None] = mapped_column(String(256))
    fetched_at: Mapped[int | None] = mapped_column(Integer)
    provenance: Mapped[dict | None] = mapped_column(JSON)


class BRTIObservation(Base):
    """Timestamped CF Benchmarks BRTI reading used by KXBTC15M resolution."""

    __tablename__ = "brti_observations"
    __table_args__ = (Index("ix_brti_available", "available_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)
    value_dollars: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    capture_session_id: Mapped[str | None] = mapped_column(String(64))
    source_endpoint: Mapped[str | None] = mapped_column(String(256))
    fetched_at: Mapped[int | None] = mapped_column(Integer)
    provenance: Mapped[dict | None] = mapped_column(JSON)


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
    # P(this decision's chosen side wins), side-consistent (kxbtc15m-
    # validation-rebuild §2.3). None for HOLDs. This is the number the engine
    # actually sizes and gates on — distinct from `bs_probability`, which is
    # a model-specific YES probability only some strategies produce.
    fair_probability: Mapped[float | None] = mapped_column(Float)
    bs_probability: Mapped[float | None] = mapped_column(Float)
    mc_probability: Mapped[float | None] = mapped_column(Float)
    raw_edge: Mapped[float | None] = mapped_column(Float)
    fee_adjusted_edge: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    hold_reason: Mapped[str | None] = mapped_column(String(128))
    context: Mapped[str | None] = mapped_column(Text)  # JSON blob of full inputs


class VetoVerdictRecord(Base):
    """Every local AI veto verdict (tasks.md 7.1/7.6), linked to the signal
    it reviewed. Persisted unconditionally — approved, rejected, AND every
    fail-closed path (malformed JSON, request failure, etc.) — so tasks.md
    7.5's benchmark question ("do verdicts correlate with realized
    outcomes at all?") can be answered from data later, and so a systematic
    fail-closed pattern (e.g. the model consistently timing out) is visible
    in the record rather than silently invisible."""

    __tablename__ = "veto_verdicts"
    __table_args__ = (Index("ix_veto_verdicts_signal", "signal_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"))
    model: Mapped[str] = mapped_column(String(128), nullable=False)

    approved: Mapped[bool] = mapped_column(nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(256), nullable=False)
    raw_response: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class ForecastRecord(Base):
    """One short-horizon price forecast (tasks.md 7.2), persisted so its
    predictive value can be measured against realized moves later (the same
    "does this signal correlate with outcomes at all?" question tasks.md 7.5
    asks of the veto).

    Persisted unconditionally — including the neutral row a fail-safe
    backend returns when it cannot produce a real forecast — so a
    systematically unavailable forecaster is visible in the data rather than
    silently absent, exactly as `VetoVerdictRecord` does for the veto.

    `backend` names the implementation that produced the row (e.g.
    ``"stub"`` / ``"chronos-bolt-small"``) so a later backend swap stays
    distinguishable in the history. Prices are USD spot floats, matching
    `SpotCandle` — this is a forecast of the underlying, not of a contract
    price.
    """

    __tablename__ = "forecasts"
    __table_args__ = (Index("ix_forecasts_signal", "signal_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"))
    backend: Mapped[str] = mapped_column(String(64), nullable=False)

    symbol: Mapped[str] = mapped_column(String(16), nullable=False)  # e.g. "BTC-USD"
    asof_ts: Mapped[int] = mapped_column(Integer, nullable=False)  # last observed bar
    horizon_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    last_price: Mapped[float] = mapped_column(Float, nullable=False)  # spot at asof_ts
    # Median (point) forecast and a symmetric-ish interval from the backend's
    # quantiles. None on a neutral fail-safe row.
    median_price: Mapped[float | None] = mapped_column(Float)
    low_price: Mapped[float | None] = mapped_column(Float)  # lower quantile
    high_price: Mapped[float | None] = mapped_column(Float)  # upper quantile

    # Convenience derived signal: expected fractional return over the horizon
    # (median_price / last_price - 1). None on a neutral row. The strategy
    # layer decides how to use it; storing it keeps benchmark queries simple.
    expected_return: Mapped[float | None] = mapped_column(Float)
    available: Mapped[bool] = mapped_column(nullable=False)  # False => neutral fail-safe row
    reason: Mapped[str] = mapped_column(String(128), nullable=False)  # "ok" | failure code
    latency_ms: Mapped[int | None] = mapped_column(Integer)


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
    # Float, not Integer: event contracts trade in whole units but the record
    # must not truncate (kxbtc15m-validation-rebuild §2.4); the same field
    # carries fractional perp sizing later.
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_ts: Mapped[int] = mapped_column(Integer, nullable=False)

    exit_price_cents: Mapped[int | None] = mapped_column(Integer)
    exit_ts: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    # open | settled_won | settled_lost | closed_early

    gross_pnl_usd: Mapped[float | None] = mapped_column(Float)
    # Each matched-order fee, recorded separately (kxbtc15m-validation-rebuild
    # §2.4). entry_fee_usd: paid on open, win or lose. exit_fee_usd: charged
    # only on an early close (a second taker order); 0 for a hold-to-expiry
    # settlement. fee_usd stays as their sum for existing readers.
    entry_fee_usd: Mapped[float | None] = mapped_column(Float)
    exit_fee_usd: Mapped[float | None] = mapped_column(Float)
    fee_usd: Mapped[float | None] = mapped_column(Float)
    net_pnl_usd: Mapped[float | None] = mapped_column(Float)
