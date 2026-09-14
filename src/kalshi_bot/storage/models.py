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
    event,
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


class PerpMarkObservation(Base):
    """One foreground snapshot of a Kalshi crypto perpetual's marks.

    Captured live by `kalshi_bot.data.perps.poll_perp_marks` — the perp
    analogue of `BRTIObservation`. Kalshi does NOT publish a historical
    mark-price series, so (unlike funding) these can only be gathered by
    polling `GET /margin/markets/{ticker}` in a foreground loop and are
    subject to the same causal discipline: `observed_at` is the exchange's
    own `settlement_mark_price.ts_ms` (seconds), `available_at` is local
    receipt time, gaps are recorded and never filled.

    All price columns are Kalshi fixed-point dollar *strings* PER CONTRACT
    (a BTC perp contract is 0.0001 BTC), kept verbatim to avoid float drift;
    `contract_size` is stored so a caller can convert to per-unit-of-index.
    """

    __tablename__ = "perp_mark_observations"
    __table_args__ = (
        UniqueConstraint("market_ticker", "observed_at", name="uq_perp_mark_ticker_observed"),
        Index("ix_perp_mark_ticker_available", "market_ticker", "available_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)  # epoch seconds
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)

    settlement_mark_dollars: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_price_dollars: Mapped[str | None] = mapped_column(String(32))
    liquidation_mark_dollars: Mapped[str | None] = mapped_column(String(32))
    bid_dollars: Mapped[str | None] = mapped_column(String(32))
    ask_dollars: Mapped[str | None] = mapped_column(String(32))
    contract_size: Mapped[str | None] = mapped_column(String(32))
    open_interest: Mapped[str | None] = mapped_column(String(32))
    leverage_estimate: Mapped[float | None] = mapped_column(Float)

    source: Mapped[str] = mapped_column(String(128), nullable=False)
    capture_session_id: Mapped[str | None] = mapped_column(String(64))
    source_endpoint: Mapped[str | None] = mapped_column(String(256))
    fetched_at: Mapped[int | None] = mapped_column(Integer)
    provenance: Mapped[dict | None] = mapped_column(JSON)


class PerpFundingObservation(Base):
    """One realized 8-hourly funding settlement for a Kalshi crypto perp.

    Unlike the mark price, Kalshi DOES serve funding history
    (`GET /margin/funding_rates/historical`), so this table is populated by a
    one-shot idempotent backfill (`kalshi_bot.data.perps.backfill_funding`)
    rather than a poll loop. `funding_rate` is a plain float (it is legitimately
    exactly 0 in many intervals); `mark_price_dollars` is the per-contract
    dollar string Kalshi reports alongside it.

    `observed_at` is the funding settlement instant (`funding_time`).
    `available_at` equals `observed_at`: a realized funding rate is knowable
    exactly at settlement, and the backfill does not fabricate an earlier
    availability it cannot support.
    """

    __tablename__ = "perp_funding_observations"
    __table_args__ = (
        UniqueConstraint("market_ticker", "observed_at", name="uq_perp_funding_ticker_observed"),
        Index("ix_perp_funding_ticker_observed", "market_ticker", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)  # settlement epoch s
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)

    funding_rate: Mapped[float] = mapped_column(Float, nullable=False)
    mark_price_dollars: Mapped[str | None] = mapped_column(String(32))

    source: Mapped[str] = mapped_column(String(128), nullable=False)
    capture_session_id: Mapped[str | None] = mapped_column(String(64))
    source_endpoint: Mapped[str | None] = mapped_column(String(256))
    fetched_at: Mapped[int | None] = mapped_column(Integer)
    provenance: Mapped[dict | None] = mapped_column(JSON)


class RawMarketArtifact(Base):
    """Immutable source artifact metadata for reproducible external history."""

    __tablename__ = "raw_market_artifacts"
    __table_args__ = (
        UniqueConstraint("source", "content_sha256", "parser_version", name="uq_raw_artifact_hash"),
        Index("ix_raw_artifacts_instrument", "venue", "native_symbol", "retrieved_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    # primary|secondary|manual_comparison
    source_role: Mapped[str] = mapped_column(String(24), nullable=False)
    venue: Mapped[str] = mapped_column(String(32), nullable=False)
    native_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    market_type: Mapped[str] = mapped_column(String(16), nullable=False)  # spot|perp|trades|book
    quote_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    retrieved_at: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_version: Mapped[str | None] = mapped_column(String(128))
    # verified|missing|rejected
    checksum_status: Mapped[str] = mapped_column(String(16), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="accepted")
    metadata_json: Mapped[dict | None] = mapped_column(JSON)


class NormalizedMarketBar(Base):
    """Normalized OHLCV bar retaining source and causal availability."""

    __tablename__ = "normalized_market_bars"
    __table_args__ = (
        # market_type belongs to the identity: Binance spot and USD-M perp share
        # a native symbol (BTCUSDT), so without it the two series collide and
        # only whichever imported first can be stored.
        UniqueConstraint(
            "source",
            "venue",
            "native_symbol",
            "market_type",
            "period_minutes",
            "open_ts",
            "parser_version",
            name="uq_normalized_bar_identity",
        ),
        Index("ix_normalized_bars_symbol_ts", "native_symbol", "open_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("raw_market_artifacts.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    venue: Mapped[str] = mapped_column(String(32), nullable=False)
    native_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(16), nullable=False)
    market_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    period_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    open_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    close_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieved_at: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_status: Mapped[str] = mapped_column(String(16), nullable=False, default="accepted")


class NormalizedAggregateTrade(Base):
    """Normalized exchange trade, with unknown aggressor direction preserved."""

    __tablename__ = "normalized_aggregate_trades"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "venue",
            "native_symbol",
            "trade_id",
            "parser_version",
            name="uq_normalized_trade_identity",
        ),
        Index("ix_normalized_trades_symbol_ts", "native_symbol", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("raw_market_artifacts.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    venue: Mapped[str] = mapped_column(String(32), nullable=False)
    native_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(16), nullable=False)
    market_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_id: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieved_at: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    aggressor_side: Mapped[str | None] = mapped_column(String(8))
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_status: Mapped[str] = mapped_column(String(16), nullable=False, default="accepted")


class DataQualityGap(Base):
    """An observed missing/invalid interval; gaps are never silently filled."""

    __tablename__ = "data_quality_gaps"
    __table_args__ = (Index("ix_data_gaps_instrument_ts", "venue", "native_symbol", "start_ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    venue: Mapped[str] = mapped_column(String(32), nullable=False)
    native_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(16), nullable=False)
    observation_type: Mapped[str] = mapped_column(String(16), nullable=False)
    start_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON)


class DatasetManifest(Base):
    """Frozen input manifest for a training/backtest/paper-admission run."""

    __tablename__ = "dataset_manifests"
    __table_args__ = (UniqueConstraint("manifest_sha256", name="uq_dataset_manifest_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    asset_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    source_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    start_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    code_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="frozen")
    coverage_summary: Mapped[dict | None] = mapped_column(JSON)
    filter_rules: Mapped[dict | None] = mapped_column(JSON)
    artifact_hashes: Mapped[list | None] = mapped_column(JSON)
    normalized_partitions: Mapped[list | None] = mapped_column(JSON)
    source_mappings: Mapped[dict | None] = mapped_column(JSON)
    provenance_class: Mapped[str | None] = mapped_column(String(16))
    reconstruction_error: Mapped[dict | None] = mapped_column(JSON)


class ReconstructedIndexObservation(Base):
    """One second of the synthetic BRTI proxy composed from constituent USD
    venues (brti-constituent-history §D3). Distinct from `brti_observations`
    by construction -- nothing here is ever readable through the captured-
    BRTI read path, and every row is explicit about how many venues, and
    which ones, contributed to it."""

    __tablename__ = "reconstructed_index_observations"
    __table_args__ = (
        UniqueConstraint(
            "target_index", "observed_at", name="uq_reconstructed_index_observed_at"
        ),
        Index("ix_reconstructed_index_observed_at", "target_index", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_index: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    value_dollars: Mapped[str] = mapped_column(String(32), nullable=False)
    contributor_count: Mapped[int] = mapped_column(Integer, nullable=False)
    contributing_venues: Mapped[list] = mapped_column(JSON, nullable=False)
    provenance: Mapped[str] = mapped_column(
        String(24), nullable=False, default="reconstructed_index"
    )
    composed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    composer_version: Mapped[str] = mapped_column(String(64), nullable=False)


class PaperRun(Base):
    """Foreground paper/shadow run identity; never a live-order run."""

    __tablename__ = "paper_runs"
    __table_args__ = (Index("ix_paper_runs_domain_started", "domain", "started_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    asset_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    started_at: Mapped[int] = mapped_column(Integer, nullable=False)
    ended_at: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    config_fingerprint: Mapped[str] = mapped_column(String(512), nullable=False)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    risk_policy_version: Mapped[str | None] = mapped_column(String(64))

    # Which strategy selected this run's behaviour, resolved through
    # `strategy/registry.py` (strategy-lab-multi-account §1.4). `strategy_id`
    # is the registered id, not a free-text label; `strategy_gate_status` is
    # the registry's standing for that strategy at run time and is never
    # altered by the run's own result (design.md D4). Nullable: runs written
    # before schema v14 have none.
    strategy_id: Mapped[str | None] = mapped_column(String(64))
    strategy_config_version: Mapped[str | None] = mapped_column(String(64))
    strategy_gate_status: Mapped[str | None] = mapped_column(String(16))
    council_profile_id: Mapped[str | None] = mapped_column(String(96))


class PaperAuditEvent(Base):
    """Append-only audit trail for every cross-domain paper lifecycle event."""

    __tablename__ = "paper_audit_events"
    __table_args__ = (Index("ix_paper_audit_run_time", "paper_run_id", "observed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_run_id: Mapped[str] = mapped_column(ForeignKey("paper_runs.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    domain: Mapped[str] = mapped_column(String(16), nullable=False)
    asset_id: Mapped[str | None] = mapped_column(String(16))
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(256))
    data_manifest_hash: Mapped[str | None] = mapped_column(String(64))
    risk_policy_version: Mapped[str | None] = mapped_column(String(64))
    council_run_id: Mapped[str | None] = mapped_column(String(64))
    council_decision_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict | None] = mapped_column(JSON)


class CouncilRunRecord(Base):
    """One immutable candidate review and its evidence/policy lineage."""

    __tablename__ = "council_runs"
    __table_args__ = (
        Index("ix_council_runs_paper_time", "paper_run_id", "created_at"),
        Index("ix_council_runs_profile_time", "profile_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_run_id: Mapped[str | None] = mapped_column(ForeignKey("paper_runs.id"))
    candidate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    domain: Mapped[str] = mapped_column(String(16), nullable=False)
    specialization_key: Mapped[str] = mapped_column(String(128), nullable=False)
    instrument_id: Mapped[str] = mapped_column(String(128), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(96), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class EvidenceBundleRecord(Base):
    """Content-addressed, point-in-time evidence used by a council run."""

    __tablename__ = "council_evidence_bundles"
    __table_args__ = (UniqueConstraint("bundle_hash", name="uq_council_evidence_bundle_hash"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    council_run_id: Mapped[str] = mapped_column(ForeignKey("council_runs.id"), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    decision_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    bundle_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class AgentDefinitionSnapshotRecord(Base):
    """Versioned role/provider/card permissions captured for one council run."""

    __tablename__ = "council_agent_definitions"
    __table_args__ = (
        Index("ix_council_agent_defs_run_role", "council_run_id", "role"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    council_run_id: Mapped[str] = mapped_column(ForeignKey("council_runs.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    capability_hash: Mapped[str | None] = mapped_column(String(64))
    permissions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class AgentVerdictRecord(Base):
    """Append-only validated verdict attempt from one council role."""

    __tablename__ = "council_agent_verdicts"
    __table_args__ = (
        UniqueConstraint(
            "council_run_id",
            "role",
            "attempt",
            "request_hash",
            name="uq_council_verdict_attempt",
        ),
        Index("ix_council_verdicts_run_role", "council_run_id", "role"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    council_run_id: Mapped[str] = mapped_column(ForeignKey("council_runs.id"), nullable=False)
    evidence_bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    verdict_json: Mapped[dict | None] = mapped_column(JSON)
    raw_output_hash: Mapped[str | None] = mapped_column(String(64))
    raw_output_redacted: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    a2a_task_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class CouncilDecisionRecord(Base):
    """Sealed master recommendation and deterministic policy result."""

    __tablename__ = "council_decisions"
    __table_args__ = (Index("ix_council_decisions_run_time", "council_run_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    council_run_id: Mapped[str] = mapped_column(ForeignKey("council_runs.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    final_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(256))
    policy_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    artifact_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class CouncilProfileLifecycleRecord(Base):
    """Append-only lifecycle history for one versioned council profile."""

    __tablename__ = "council_profile_lifecycle"
    __table_args__ = (Index("ix_council_profile_lifecycle", "profile_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[str] = mapped_column(String(96), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    from_state: Mapped[str] = mapped_column(String(24), nullable=False)
    to_state: Mapped[str] = mapped_column(String(24), nullable=False)
    operator: Mapped[str | None] = mapped_column(String(64))
    report_id: Mapped[str | None] = mapped_column(String(96))
    reason: Mapped[str] = mapped_column(String(256), nullable=False)
    gate_results: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


def _reject_council_mutation(*_args, **_kwargs) -> None:
    """Council lineage is append-only; corrections are new attempts/rows."""

    raise ValueError("council lineage records are append-only")


for _append_only_model in (
    CouncilRunRecord,
    EvidenceBundleRecord,
    AgentDefinitionSnapshotRecord,
    AgentVerdictRecord,
    CouncilDecisionRecord,
    CouncilProfileLifecycleRecord,
):
    event.listen(_append_only_model, "before_update", _reject_council_mutation)
    event.listen(_append_only_model, "before_delete", _reject_council_mutation)


class PerpPaperPosition(Base):
    """Independent linear-perpetual paper position; never a binary trade."""

    __tablename__ = "perp_paper_positions"
    __table_args__ = (Index("ix_perp_position_run_status", "paper_run_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_run_id: Mapped[str] = mapped_column(ForeignKey("paper_runs.id"), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(16), nullable=False)
    market_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    signed_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    entry_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    realized_pnl_usd: Mapped[float | None] = mapped_column(Float)
    funding_pnl_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fee_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class PerpPaperEvent(Base):
    """Append-only perp fill, mark, funding, margin, bracket, or reconciliation event."""

    __tablename__ = "perp_paper_events"
    __table_args__ = (Index("ix_perp_event_position_ts", "position_id", "observed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("perp_paper_positions.id"))
    paper_run_id: Mapped[str] = mapped_column(ForeignKey("paper_runs.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float | None] = mapped_column(Float)
    quantity: Mapped[float | None] = mapped_column(Float)
    funding_rate: Mapped[float | None] = mapped_column(Float)
    margin_usd: Mapped[float | None] = mapped_column(Float)
    liquidation_price: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(256))
    quote_reference: Mapped[dict | None] = mapped_column(JSON)
    payload: Mapped[dict | None] = mapped_column(JSON)


class PerpFundingEstimateObservation(Base):
    """One point-in-time funding-rate estimate for a Kalshi crypto perp.

    Unlike a realized funding settlement, an estimate changes during the
    current funding interval and is not recoverable from Kalshi later. The
    operator capture command records it with the exchange's ``computed_time``
    as ``observed_at`` and local receipt as ``available_at``. This makes an
    estimate usable only after the bot could actually have received it.
    """

    __tablename__ = "perp_funding_estimate_observations"
    __table_args__ = (
        UniqueConstraint(
            "market_ticker", "observed_at", name="uq_perp_funding_estimate_ticker_observed"
        ),
        Index("ix_perp_funding_estimate_ticker_available", "market_ticker", "available_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)

    funding_rate: Mapped[float] = mapped_column(Float, nullable=False)
    mark_price_dollars: Mapped[str | None] = mapped_column(String(32))
    next_funding_time: Mapped[str | None] = mapped_column(String(64))

    source: Mapped[str] = mapped_column(String(128), nullable=False)
    capture_session_id: Mapped[str | None] = mapped_column(String(64))
    source_endpoint: Mapped[str | None] = mapped_column(String(256))
    fetched_at: Mapped[int | None] = mapped_column(Integer)
    provenance: Mapped[dict | None] = mapped_column(JSON)


class SportsSeries(Base):
    """Immutable-ish point-in-time metadata for a discovered sports series."""

    __tablename__ = "sports_series"
    __table_args__ = (Index("ix_sports_series_sport_observed", "sport", "observed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    sport: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(256))
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)
    source_endpoint: Mapped[str | None] = mapped_column(String(256))
    capture_session_id: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict | None] = mapped_column(JSON)


class SportsMarketRuleProvenance(Base):
    """Versioned rules/settlement snapshot used to classify a sports market."""

    __tablename__ = "sports_market_rule_provenance"
    __table_args__ = (Index("ix_sports_rules_market_observed", "market_ticker", "observed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    settlement_source: Mapped[str | None] = mapped_column(String(256))
    outcome_shape: Mapped[str | None] = mapped_column(String(32))
    rules_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_endpoint: Mapped[str | None] = mapped_column(String(256))
    capture_session_id: Mapped[str | None] = mapped_column(String(64))


class SportsMarketDiscovery(Base):
    """One screening result per market observation, including rejected rows."""

    __tablename__ = "sports_market_discovery"
    __table_args__ = (
        Index("ix_sports_discovery_market_observed", "market_ticker", "observed_at"),
        Index("ix_sports_discovery_eligible", "eligible", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    market_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    sport: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(256))
    event_ticker: Mapped[str | None] = mapped_column(String(64))
    close_ts: Mapped[int | None] = mapped_column(Integer)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str | None] = mapped_column(String(16))
    outcome_shape: Mapped[str | None] = mapped_column(String(32))
    settlement_source: Mapped[str | None] = mapped_column(String(256))
    fee_metadata: Mapped[dict | None] = mapped_column(JSON)
    yes_bid_cents: Mapped[int | None] = mapped_column(Integer)
    yes_ask_cents: Mapped[int | None] = mapped_column(Integer)
    bid_size: Mapped[float | None] = mapped_column(Float)
    ask_size: Mapped[float | None] = mapped_column(Float)
    open_interest: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    spread_cents: Mapped[int | None] = mapped_column(Integer)
    eligible: Mapped[bool] = mapped_column(nullable=False, default=False)
    failure_reason: Mapped[str | None] = mapped_column(String(128))
    rule_provenance_id: Mapped[int | None] = mapped_column(Integer)
    raw_metadata: Mapped[dict | None] = mapped_column(JSON)
    source_endpoint: Mapped[str | None] = mapped_column(String(256))
    capture_session_id: Mapped[str | None] = mapped_column(String(64))


class SportsCandle(Base):
    """Point-in-time sports candle; kept separate from crypto candles."""

    __tablename__ = "sports_candles"
    __table_args__ = (
        UniqueConstraint(
            "market_ticker", "period_minutes", "end_period_ts", name="uq_sports_candle"
        ),
        Index("ix_sports_candles_market_ts", "market_ticker", "end_period_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    market_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    period_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    end_period_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)
    yes_bid_cents: Mapped[int | None] = mapped_column(Integer)
    yes_ask_cents: Mapped[int | None] = mapped_column(Integer)
    yes_bid_size: Mapped[float | None] = mapped_column(Float)
    yes_ask_size: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    open_interest: Mapped[float | None] = mapped_column(Float)
    source_endpoint: Mapped[str | None] = mapped_column(String(256))
    capture_session_id: Mapped[str | None] = mapped_column(String(64))
    provenance: Mapped[dict | None] = mapped_column(JSON)


class SportsOrderBookSnapshot(Base):
    """Raw public L2 snapshot with causal exchange and receipt timestamps."""

    __tablename__ = "sports_order_book_snapshots"
    __table_args__ = (Index("ix_sports_l2_market_available", "market_ticker", "available_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    market_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)
    bids: Mapped[list | dict] = mapped_column(JSON, nullable=False)
    asks: Mapped[list | dict] = mapped_column(JSON, nullable=False)
    source_endpoint: Mapped[str | None] = mapped_column(String(256))
    capture_session_id: Mapped[str | None] = mapped_column(String(64))
    provenance: Mapped[dict | None] = mapped_column(JSON)


class SportsPublicTrade(Base):
    """Public sports trade observation."""

    __tablename__ = "sports_public_trades"
    __table_args__ = (Index("ix_sports_trades_market_available", "market_ticker", "available_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    market_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    taker_side: Mapped[str | None] = mapped_column(String(8))
    trade_id: Mapped[str | None] = mapped_column(String(128))
    source_endpoint: Mapped[str | None] = mapped_column(String(256))
    capture_session_id: Mapped[str | None] = mapped_column(String(64))
    provenance: Mapped[dict | None] = mapped_column(JSON)


class SportsCaptureGap(Base):
    """An observed missing interval; no synthetic row is inserted."""

    __tablename__ = "sports_capture_gaps"
    __table_args__ = (Index("ix_sports_gaps_market_start", "market_ticker", "start_ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    start_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_interval_s: Mapped[int] = mapped_column(Integer, nullable=False)
    capture_session_id: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(128), nullable=False, default="capture_gap")


class SportsFlowFeature(Base):
    """Versioned anonymous flow feature window used by research only."""

    __tablename__ = "sports_flow_features"
    __table_args__ = (
        UniqueConstraint(
            "market_ticker", "window_end_ts", "feature_version", name="uq_sports_flow_window"
        ),
        Index("ix_sports_flow_market_available", "market_ticker", "available_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    market_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    window_start_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    window_end_ts: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_window_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    features: Mapped[dict] = mapped_column(JSON, nullable=False)
    identity_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unavailable")
    capture_session_id: Mapped[str | None] = mapped_column(String(64))
    provenance: Mapped[dict | None] = mapped_column(JSON)


class SportsEvidenceCard(Base):
    """Append-only, attributable external evidence observation."""

    __tablename__ = "sports_evidence_cards"
    __table_args__ = (
        Index("ix_sports_evidence_market_available", "market_ticker", "available_at"),
        Index("ix_sports_evidence_source_hash", "provider", "raw_content_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_ticker: Mapped[str | None] = mapped_column(String(64))
    market_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(512), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[int | None] = mapped_column(Integer)
    publication_at: Mapped[int | None] = mapped_column(Integer)
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieved_at: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_domain: Mapped[str | None] = mapped_column(String(256))
    citations: Mapped[list | None] = mapped_column(JSON)
    raw_content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="usable")
    provenance: Mapped[dict | None] = mapped_column(JSON)


class SportsLLMReview(Base):
    """Auditable structured local/hosted research review; never an order."""

    __tablename__ = "sports_llm_reviews"
    __table_args__ = (Index("ix_sports_llm_market_available", "market_ticker", "available_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str | None] = mapped_column(String(64))
    citations: Mapped[list | None] = mapped_column(JSON)
    summary: Mapped[str | None] = mapped_column(Text)
    classification: Mapped[str | None] = mapped_column(String(32))
    available_at: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieved_at: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_output: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[dict | None] = mapped_column(JSON)


class CryptoRegistrySnapshot(Base):
    """Immutable registry/configuration snapshot used for audit and replay."""

    __tablename__ = "crypto_registry_snapshots"
    __table_args__ = (UniqueConstraint("registry_version", name="uq_registry_snapshot_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    registry_version: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[int] = mapped_column(Integer, nullable=False)
    registry_json: Mapped[list | dict] = mapped_column(JSON, nullable=False)


class DiscoveryResult(Base):
    """Latest or historical result of explicit event/perp discovery."""

    __tablename__ = "discovery_results"
    __table_args__ = (Index("ix_discovery_asset_instrument", "asset_id", "instrument", "cadence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(String(16), nullable=False)
    instrument: Mapped[str] = mapped_column(String(16), nullable=False)  # event|perp
    cadence: Mapped[str | None] = mapped_column(String(8))
    identifier: Mapped[str] = mapped_column(String(64), nullable=False)
    checked_at: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible: Mapped[bool] = mapped_column(nullable=False, default=False)
    failure_reason: Mapped[str | None] = mapped_column(String(256))
    metadata_json: Mapped[dict | None] = mapped_column(JSON)


class AssetRunRecord(Base):
    """Asset-attributed collection/backtest/admission run record."""

    __tablename__ = "asset_run_records"
    __table_args__ = (Index("ix_asset_runs_asset_time", "asset_id", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(String(16), nullable=False)
    cadence: Mapped[str | None] = mapped_column(String(8))
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[int] = mapped_column(Integer, nullable=False)
    ended_at: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON)


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


class EmergencyHaltRecord(Base):
    """Durable, append-only global emergency-control state (multi-venue §11.4/11.5).

    One row per state change. The current state is the highest-``id`` row: a
    ``halt`` row halts every paper domain until a later ``resume`` row for the
    same ``halt_id`` is written by an explicit operator action. A new process
    start reads the latest row and never clears a halt on its own.
    """

    __tablename__ = "emergency_halt_records"
    __table_args__ = (Index("ix_emergency_halt_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    halt_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # halt | resume
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    # operator | drawdown | daily_loss | consecutive_loss | liquidation |
    # margin_breach | data_integrity | process_signal | reconciliation
    reason: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    paper_run_id: Mapped[str | None] = mapped_column(String(64))
    domain: Mapped[str | None] = mapped_column(String(16))
    asset_id: Mapped[str | None] = mapped_column(String(16))
    operator: Mapped[str | None] = mapped_column(String(64))  # required on resume
    policy_version: Mapped[str | None] = mapped_column(String(64))
    policy_snapshot: Mapped[dict | None] = mapped_column(JSON)
    health_snapshot: Mapped[dict | None] = mapped_column(JSON)  # resume: fresh check


class LifecycleTransitionRecord(Base):
    """Auditable promotion/demotion history per asset/domain/candidate (§11.6).

    Never records a transition to ``live``. Promotions carry the frozen
    data/model/risk fingerprints and the gate results that justified them;
    demotions carry the trigger that forced the scope back to ``blocked`` or an
    earlier state. Unrelated scopes are untouched.
    """

    __tablename__ = "lifecycle_transition_records"
    __table_args__ = (Index("ix_lifecycle_transition_scope", "scope_key", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_key: Mapped[str] = mapped_column(String(96), nullable=False)  # ASSET:domain:candidate
    asset_id: Mapped[str] = mapped_column(String(16), nullable=False)
    domain: Mapped[str] = mapped_column(String(16), nullable=False)
    candidate: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)  # promote | demote
    from_state: Mapped[str] = mapped_column(String(16), nullable=False)
    to_state: Mapped[str] = mapped_column(String(16), nullable=False)
    trigger: Mapped[str] = mapped_column(String(48), nullable=False)
    reason: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    operator: Mapped[str | None] = mapped_column(String(64))
    report_id: Mapped[str | None] = mapped_column(String(64))
    data_manifest_hash: Mapped[str | None] = mapped_column(String(64))
    model_fingerprint: Mapped[str | None] = mapped_column(String(64))
    risk_policy_version: Mapped[str | None] = mapped_column(String(64))
    gate_results: Mapped[dict | None] = mapped_column(JSON)


class DashboardSetting(Base):
    """Single operator-facing dashboard preference, stored server-side.

    Key-value rather than one column per setting: the dashboard is one
    operator's tool, not multi-tenant, so a small open-ended JSON value per
    key avoids a migration for every new preference (theme colors today,
    anything else later). Read once at process start and cached in-process;
    a write updates both.
    """

    __tablename__ = "dashboard_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
