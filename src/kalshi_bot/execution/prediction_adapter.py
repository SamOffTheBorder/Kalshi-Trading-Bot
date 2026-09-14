"""Prediction-market domain adapter behind the shared orchestrator (§8.5/§8.6).

This keeps the KXBTC15M loop's execution discipline — marketable limit fills
only, side-aware worst-of-quote pricing, the taker fee at entry, a signal row
for every evaluation (HOLD included), official settlement, and restart
recovery from `SimulatedTrade` rows — but exposes it through the domain-
neutral `DomainPaperAdapter` envelope the orchestrator routes to.

It is generalized across separately-admitted BTC/ETH/SOL/XRP contracts by
resolving each asset's active series from the crypto registry and refusing to
act on an asset with no fresh listed market (§8.6): a stale or guessed ticker
is never used.

`may_fill=False` (a shadow-lifecycle asset, or a shadow-mode run) still
produces a full decision and records the observable would-fill, but never
calls `place_order` — that is §8.7 shadow mode with no separate code path.

Strategy seam (strategy-lab-multi-account §2): the adapter drives a
`StrategyProtocol` object — the same object the backtest engine and
walk-forward harness run — by assembling a `StrategyContext` for each
evaluation via `StrategyContextBuilder`. Context assembly is causal by
construction: every historical input is filtered on `available_at <= now_ts`
(BRTI) or `open_ts < now_ts` (spot bars), mirroring
`BacktestEngine._bars_before`'s look-ahead discipline. A missing input leaves
its context field unset (`trend_zscore=None`, empty `spot_bars`/
`brti_readings`, sentinel `spot=0.0`) and the strategy decides — the adapter
never forward-fills or substitutes a default value.

The legacy `StrategyFn` callable (`Callable[[PredictionQuote],
StrategySignal]`) is retained only for the sports domain and for existing
tests that inject a quote->signal lambda; when `strategy` is a
`StrategyProtocol` object the context path is used.
"""

from __future__ import annotations

import asyncio
import bisect
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from kalshi_bot.config.crypto_registry import (
    DEFAULT_CRYPTO_REGISTRY,
    CryptoAssetConfig,
)
from kalshi_bot.config.lifecycle import Domain
from kalshi_bot.execution.broker_protocol import MarketSnapshot, OrderRequest
from kalshi_bot.execution.orchestrator import AdapterDecision, ReconciliationOutcome
from kalshi_bot.execution.paper_broker import PaperBroker
from kalshi_bot.signals.settlement_window import BRTIReading
from kalshi_bot.signals.volatility import estimate_volatility
from kalshi_bot.storage.models import BRTIObservation, KalshiMarket, SimulatedTrade, SpotCandle
from kalshi_bot.strategy.base import Action, Decision, StrategyContext
from kalshi_bot.strategy.levels import SpotBar

# BTC index labels accepted for the KXBTC15M settlement series — same set the
# backtest engine filters `BRTIObservation` by, so a paper run never mixes
# another CF Benchmarks index into the settlement calculation.
_BTC_BRTI_SOURCE_LABELS = ("brti", "BRTI", "kalshi:cfbenchmarks/BRTI")

# How far back the per-evaluation BRTI slice reaches: the 15-minute market
# lifetime plus the 60 s reference average and a short-horizon trend lookback.
_BRTI_SLICE_WINDOW_S = 1_800

# Asset id -> spot symbol for the SpotCandle / volatility inputs.
_ASSET_SPOT_SYMBOL = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "XRP": "XRP-USD",
}

_TREND_LOOKBACK_S = 86_400
_SPOT_BAR_WINDOW = 48


@dataclass(frozen=True)
class PredictionQuote:
    """One point-in-time listed market for an asset."""

    asset_id: str
    market_ticker: str
    series_ticker: str
    close_ts: int
    observed_at: int
    yes_bid_cents: int | None
    yes_ask_cents: int | None
    result: str | None = None  # set once the market resolved
    strike_type: str | None = None  # greater | less | between
    floor_strike: float | None = None
    cap_strike: float | None = None


# A legacy strategy callable: turns a quote into a coarse buy/hold signal.
# Retained for the sports domain and for tests that inject a lambda; a
# `StrategyProtocol` object is the real path (see module docstring).
StrategyFn = Callable[[PredictionQuote], "StrategySignal"]


@dataclass(frozen=True)
class StrategySignal:
    action: str  # "hold" | "buy"
    side: str | None = None  # "yes" | "no"
    limit_price_cents: int | None = None
    quantity: int = 1
    reason: str | None = None
    meta: dict[str, object] = field(default_factory=dict)


def hold_strategy(_quote: PredictionQuote) -> StrategySignal:
    return StrategySignal(action="hold", reason="no_strategy_configured")


def _is_strategy_protocol(obj: object) -> bool:
    """True when `obj` is a `StrategyProtocol` (has `evaluate` + `name`),
    rather than a plain `StrategyFn` callable."""
    return hasattr(obj, "evaluate") and hasattr(obj, "name") and not isinstance(obj, type)


# --------------------------------------------------------------------------
# Strategy context assembly (§2.1-2.3)
# --------------------------------------------------------------------------


class StrategyContextBuilder:
    """Assembles a `StrategyContext` for one (quote, now_ts) pair.

    Spot close/OHLCV history and BRTI readings are loaded once per asset and
    cached for the run's lifetime, then sliced per evaluation with a bisect —
    the same shape `BacktestEngine` uses. Every slice is causal: BRTI on
    `available_at <= now_ts`, spot bars on `open_ts < now_ts`, spot/vol on the
    latest close at-or-before `now_ts - stride`.
    """

    def __init__(
        self,
        session: Session,
        *,
        trend_lookback_s: int = _TREND_LOOKBACK_S,
        spot_bar_window: int = _SPOT_BAR_WINDOW,
    ) -> None:
        self._session = session
        self._trend_lookback_s = trend_lookback_s
        self._spot_bar_window = spot_bar_window
        self._hourly: dict[str, tuple[list[int], list[float]]] = {}
        self._daily: dict[str, tuple[list[int], list[float]]] = {}
        self._bars: dict[str, tuple[list[int], list[SpotBar]]] = {}
        self._brti: tuple[list[int], tuple[BRTIReading, ...]] | None = None

    # -- loaders (cached per asset / run) --------------------------------

    def _load_close(self, symbol: str, period_minutes: int) -> tuple[list[int], list[float]]:
        rows = self._session.execute(
            select(SpotCandle.open_ts, SpotCandle.close)
            .where(SpotCandle.symbol == symbol, SpotCandle.period_minutes == period_minutes)
            .order_by(SpotCandle.open_ts)
        ).all()
        by_ts: dict[int, float] = {ts: close for ts, close in rows}
        sorted_ts = sorted(by_ts)
        return sorted_ts, [by_ts[t] for t in sorted_ts]

    def _load_bars(self, symbol: str) -> tuple[list[int], list[SpotBar]]:
        rows = self._session.execute(
            select(SpotCandle)
            .where(SpotCandle.symbol == symbol, SpotCandle.period_minutes == 60)
            .order_by(SpotCandle.open_ts)
        ).scalars()
        by_ts: dict[int, SpotBar] = {}
        for row in rows:
            by_ts[row.open_ts] = SpotBar(
                ts=row.open_ts,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
            )
        ordered = [by_ts[t] for t in sorted(by_ts)]
        return [b.ts for b in ordered], ordered

    def _hourly_for(self, symbol: str) -> tuple[list[int], list[float]]:
        if symbol not in self._hourly:
            self._hourly[symbol] = self._load_close(symbol, 60)
        return self._hourly[symbol]

    def _daily_for(self, symbol: str) -> tuple[list[int], list[float]]:
        if symbol not in self._daily:
            self._daily[symbol] = self._load_close(symbol, 1440)
        return self._daily[symbol]

    def _bars_for(self, symbol: str) -> tuple[list[int], list[SpotBar]]:
        if symbol not in self._bars:
            self._bars[symbol] = self._load_bars(symbol)
        return self._bars[symbol]

    def _load_brti(self) -> tuple[list[int], tuple[BRTIReading, ...]]:
        if self._brti is not None:
            return self._brti
        rows = self._session.execute(
            select(BRTIObservation)
            .where(
                or_(
                    BRTIObservation.source.is_(None),
                    BRTIObservation.source.in_(_BTC_BRTI_SOURCE_LABELS),
                    BRTIObservation.source.ilike("%brti%"),
                )
            )
            .order_by(BRTIObservation.available_at)
        ).scalars()
        readings = tuple(
            BRTIReading(
                observed_at=r.observed_at,
                value=float(r.value_dollars),
                available_at=r.available_at,
            )
            for r in rows
        )
        self._brti = ([r.usable_at for r in readings], readings)
        return self._brti

    # -- per-evaluation slices ----------------------------------------

    @staticmethod
    def _latest_before(ts_list: list[int], values: list[float], ts: int) -> float | None:
        idx = bisect.bisect_right(ts_list, ts) - 1
        return values[idx] if idx >= 0 else None

    def _bars_before(self, symbol: str, ts: int) -> tuple[SpotBar, ...]:
        bar_ts, bars = self._bars_for(symbol)
        idx = bisect.bisect_left(bar_ts, ts)
        return tuple(bars[max(0, idx - self._spot_bar_window) : idx])

    def _brti_before(self, ts: int) -> tuple[BRTIReading, ...]:
        usable_ts, readings = self._load_brti()
        hi = bisect.bisect_right(usable_ts, ts)
        lo = bisect.bisect_left(usable_ts, ts - _BRTI_SLICE_WINDOW_S, 0, hi)
        return readings[lo:hi]

    # -- build --------------------------------------------------------

    def build(self, quote: PredictionQuote, *, now_ts: int) -> StrategyContext:
        symbol = _ASSET_SPOT_SYMBOL.get(quote.asset_id.upper())

        spot = 0.0
        vol_annual = 0.0
        vol_source = "unavailable"
        trend_zscore: float | None = None
        spot_bars: tuple[SpotBar, ...] = ()

        if symbol is not None:
            hourly_ts, hourly_close = self._hourly_for(symbol)
            daily_ts, daily_close = self._daily_for(symbol)

            spot_val = self._latest_before(hourly_ts, hourly_close, now_ts)
            if spot_val is not None:
                spot = spot_val

            cutoff = bisect.bisect_right(daily_ts, now_ts)
            try:
                vol = estimate_volatility(daily_close[:cutoff])
            except ValueError:
                vol = None
            if vol is not None:
                vol_annual = vol.vol_annual
                vol_source = vol.source

            spot_then = self._latest_before(
                hourly_ts, hourly_close, now_ts - self._trend_lookback_s
            )
            if (
                spot_val is not None
                and spot_then is not None
                and spot_then > 0
                and vol_annual > 0
            ):
                lookback_years = self._trend_lookback_s / (365 * 24 * 3600)
                trend_zscore = math.log(spot_val / spot_then) / (
                    vol_annual * math.sqrt(lookback_years)
                )

            spot_bars = self._bars_before(symbol, now_ts)

        return StrategyContext(
            market_ticker=quote.market_ticker,
            series_ticker=quote.series_ticker,
            strike_type=quote.strike_type or "greater",
            floor_strike=quote.floor_strike,
            cap_strike=quote.cap_strike,
            now_ts=now_ts,
            close_ts=quote.close_ts,
            yes_bid_cents=quote.yes_bid_cents,
            yes_ask_cents=quote.yes_ask_cents,
            spot=spot,
            vol_annual=vol_annual,
            vol_source=vol_source,
            trend_zscore=trend_zscore,
            spot_bars=spot_bars,
            brti_readings=self._brti_before(now_ts),
        )


def _decision_to_signal(decision: Decision) -> StrategySignal:
    """Translate a `StrategyProtocol` `Decision` into the adapter's coarse
    buy/hold `StrategySignal`. HOLD -> hold; BUY_YES/BUY_NO -> buy with the
    side-consistent executable price the decision already carries."""
    if decision.action == Action.HOLD:
        return StrategySignal(
            action="hold",
            reason=decision.hold_reason or "strategy_hold",
            meta={"strategy_name": decision.strategy_name},
        )

    side = "yes" if decision.action == Action.BUY_YES else "no"
    meta: dict[str, object] = {
        "strategy_name": decision.strategy_name,
        "fair_probability": decision.fair_probability,
        "fee_adjusted_edge": decision.fee_adjusted_edge,
    }
    if decision.model_meta:
        meta["model_meta"] = decision.model_meta
    limit = decision.entry_price_cents
    if limit is None and decision.max_entry_price_cents is not None:
        limit = decision.max_entry_price_cents
    return StrategySignal(
        action="buy",
        side=side,
        limit_price_cents=limit,
        quantity=1,
        reason=None,
        meta=meta,
    )


@dataclass
class PredictionPaperAdapter:
    """Shared-envelope wrapper over `PaperBroker` for one paper run."""

    session: Session
    quote_source: Callable[[str, int], PredictionQuote | None]
    settlement_source: Callable[[str], str | None]
    starting_cash_usd: float
    strategy: StrategyFn | object = hold_strategy
    registry: Sequence[CryptoAssetConfig] = DEFAULT_CRYPTO_REGISTRY
    max_data_age_seconds: int = 120

    domain: Domain = "prediction"
    broker_name: str = "paper"

    _broker: PaperBroker = field(init=False)
    _open_by_asset: dict[str, str] = field(default_factory=dict, init=False)
    _context_builder: StrategyContextBuilder | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._broker = PaperBroker(self.session, starting_cash_usd=self.starting_cash_usd)
        # Map restored open positions back to their asset via the registry.
        for ticker in self._broker.open_position_tickers():
            asset = self._asset_for_ticker(ticker)
            if asset is not None:
                self._open_by_asset[asset] = ticker
        if _is_strategy_protocol(self.strategy):
            self._context_builder = StrategyContextBuilder(self.session)

    # -- registry resolution -----------------------------------------

    def _series_for_asset(self, asset_id: str) -> tuple[str, ...]:
        for asset in self.registry:
            if asset.asset_id == asset_id.upper():
                return tuple(
                    inst.series_ticker
                    for inst in asset.event_instruments.values()
                    if inst.series_ticker
                )
        return ()

    def _asset_for_ticker(self, ticker: str) -> str | None:
        for asset in self.registry:
            for inst in asset.event_instruments.values():
                if inst.series_ticker and ticker.startswith(inst.series_ticker):
                    return asset.asset_id
        return None

    # -- strategy dispatch ------------------------------------------

    def _run_strategy(self, quote: PredictionQuote, now_ts: int) -> StrategySignal:
        """Evaluate the configured strategy for one quote.

        A `StrategyProtocol` object gets a causally-assembled
        `StrategyContext`; a legacy `StrategyFn` callable gets the raw quote.
        """
        if self._context_builder is not None:
            context = self._context_builder.build(quote, now_ts=now_ts)
            decision = self.strategy.evaluate(context)  # type: ignore[union-attr]
            return _decision_to_signal(decision)
        return self.strategy(quote)  # type: ignore[operator]

    # -- DomainPaperAdapter ---------------------------------------

    def reconcile(self, asset_id: str) -> ReconciliationOutcome:
        """Settle any restored open position whose official result is now
        available; block new entries otherwise (§8.8)."""
        rows = list(
            self.session.execute(
                select(SimulatedTrade).where(
                    SimulatedTrade.mode == "paper",
                    SimulatedTrade.status == "open",
                )
            ).scalars()
        )
        my_rows = [r for r in rows if self._asset_for_ticker(r.market_ticker) == asset_id]
        if not my_rows:
            return ReconciliationOutcome(asset_id, True, "no_open_positions")

        unresolved: list[str] = []
        settled: list[str] = []
        for row in my_rows:
            result = self.settlement_source(row.market_ticker)
            if result in ("yes", "no"):
                net = self._broker.settle_market(row.market_ticker, result, row.entry_ts)
                self.session.commit()
                settled.append(f"{row.market_ticker}:{result}:{net:.2f}")
                self._open_by_asset.pop(asset_id, None)
            else:
                unresolved.append(row.market_ticker)

        if unresolved:
            return ReconciliationOutcome(
                asset_id,
                False,
                "open_position_without_official_result",
                {"unresolved": unresolved, "settled": settled},
            )
        return ReconciliationOutcome(
            asset_id, True, "reconciled", {"settled": settled}
        )

    def evaluate(self, asset_id: str, *, now_ts: int, may_fill: bool) -> AdapterDecision:
        series = self._series_for_asset(asset_id)
        if not series:
            return AdapterDecision(
                asset_id, self.domain, "no_market", "asset_not_in_registry",
                reason="no_series_mapping",
            )

        quote = self.quote_source(asset_id, now_ts)
        if quote is None:
            return AdapterDecision(
                asset_id, self.domain, "no_market", "no_listed_market",
                reason="discovery_found_no_fresh_market",
            )
        if now_ts - quote.observed_at > self.max_data_age_seconds:
            return AdapterDecision(
                asset_id, self.domain, "blocked", "stale_quote",
                reason=f"quote_age_{now_ts - quote.observed_at}s",
                payload={"market_ticker": quote.market_ticker},
            )

        signal = self._run_strategy(quote, now_ts)
        base_payload: dict[str, object] = {
            "market_ticker": quote.market_ticker,
            "series_ticker": quote.series_ticker,
            "yes_bid_cents": quote.yes_bid_cents,
            "yes_ask_cents": quote.yes_ask_cents,
            **signal.meta,
        }

        if signal.action != "buy":
            return AdapterDecision(
                asset_id, self.domain, "hold", "hold",
                reason=signal.reason or "strategy_hold",
                payload=base_payload,
            )

        if asset_id in self._open_by_asset:
            return AdapterDecision(
                asset_id, self.domain, "blocked", "position_already_open",
                reason="one_position_per_asset",
                payload=base_payload,
            )
        if signal.side not in ("yes", "no") or signal.limit_price_cents is None:
            return AdapterDecision(
                asset_id, self.domain, "blocked", "invalid_signal",
                reason="buy_needs_side_and_limit",
                payload=base_payload,
            )

        # A would-fill check: is the current quote marketable at the limit?
        would_fill = self._would_fill(quote, signal.side, signal.limit_price_cents)
        base_payload["would_fill_price_cents"] = would_fill

        if not may_fill:
            # Shadow: record the observable would-fill, create nothing (§8.7).
            shadow_status = "shadow_would_fill" if would_fill else "shadow_no_fill"
            return AdapterDecision(
                asset_id, self.domain, "entry", shadow_status,
                reason="shadow_mode_no_paper_fill",
                would_fill=would_fill is not None,
                payload=base_payload,
            )

        self._broker.set_current_quote(
            MarketSnapshot(
                market_ticker=quote.market_ticker,
                ts=quote.observed_at,
                yes_bid_cents=quote.yes_bid_cents,
                yes_ask_cents=quote.yes_ask_cents,
            )
        )
        result = asyncio.run(
            self._broker.place_order(
                OrderRequest(
                    market_ticker=quote.market_ticker,
                    side=signal.side,  # type: ignore[arg-type]
                    quantity=max(1, int(signal.quantity)),
                    limit_price_cents=signal.limit_price_cents,
                )
            )
        )
        self.session.commit()
        if result.status == "filled":
            self._open_by_asset[asset_id] = quote.market_ticker
            return AdapterDecision(
                asset_id, self.domain, "entry", "filled",
                reason=None,
                would_fill=True,
                filled=True,
                payload={
                    **base_payload,
                    "fill_price_cents": result.fill_price_cents,
                    "quantity": result.quantity,
                    "order_id": result.order_id,
                },
            )
        return AdapterDecision(
            asset_id, self.domain, "blocked", "order_rejected",
            reason=result.reject_reason,
            payload=base_payload,
        )

    # -- helpers ---------------------------------------------------

    @staticmethod
    def _would_fill(quote: PredictionQuote, side: str, limit_cents: int) -> int | None:
        if side == "yes":
            price = quote.yes_ask_cents
        else:
            price = None if quote.yes_bid_cents is None else 100 - quote.yes_bid_cents
        if price is None or not 1 <= price <= 99:
            return None
        return price if price <= limit_cents else None


def registry_quote_source(
    quotes: Mapping[str, PredictionQuote],
) -> Callable[[str, int], PredictionQuote | None]:
    """Build a quote source from a static asset->quote map (tests, fixtures)."""

    def _source(asset_id: str, _now_ts: int) -> PredictionQuote | None:
        return quotes.get(asset_id)

    return _source


def _yes_cents(dollars_str: str | None) -> int | None:
    if not dollars_str:
        return None
    try:
        cents = round(float(dollars_str) * 100)
    except (TypeError, ValueError):
        return None
    return cents if 1 <= cents <= 99 else None


def _iso_to_ts(value: str | None) -> int | None:
    if not value:
        return None
    from datetime import datetime

    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def kalshi_public_quote_source(
    client: object,
    *,
    registry: Sequence[CryptoAssetConfig] = DEFAULT_CRYPTO_REGISTRY,
) -> Callable[[str, int], PredictionQuote | None]:
    """Live top-of-book quote source over the unauthenticated ``/markets``
    listing — the same feed the legacy KXBTC15M loop polls (§8.5/§8.6).

    It picks the nearest-to-close open market for the asset's 15-minute
    series and returns ``None`` (never a stale/guessed ticker) when discovery
    finds nothing fresh.
    """

    series_by_asset: dict[str, str] = {}
    for asset in registry:
        inst = asset.event_instruments.get("15m")
        if inst is not None and inst.series_ticker:
            series_by_asset[asset.asset_id] = inst.series_ticker

    def _source(asset_id: str, now_ts: int) -> PredictionQuote | None:
        series = series_by_asset.get(asset_id.upper())
        if series is None:
            return None
        try:
            markets, _ = client.get_markets(  # type: ignore[attr-defined]
                series_ticker=series, status="open", limit=50
            )
        except Exception:
            return None
        best: PredictionQuote | None = None
        for m in markets:
            close_ts = _iso_to_ts(m.get("close_time"))
            if close_ts is None or close_ts <= now_ts:
                continue
            quote = PredictionQuote(
                asset_id=asset_id.upper(),
                market_ticker=m["ticker"],
                series_ticker=m.get("series_ticker", series),
                close_ts=close_ts,
                observed_at=now_ts,
                yes_bid_cents=_yes_cents(m.get("yes_bid_dollars")),
                yes_ask_cents=_yes_cents(m.get("yes_ask_dollars")),
                strike_type=m.get("strike_type"),
                floor_strike=_float_or_none(m.get("floor_strike")),
                cap_strike=_float_or_none(m.get("cap_strike")),
            )
            if best is None or quote.close_ts < best.close_ts:
                best = quote
        return best

    return _source


def db_settlement_source(session: Session) -> Callable[[str], str | None]:
    """Official Kalshi result lookup by market ticker."""

    def _source(market_ticker: str) -> str | None:
        row = session.execute(
            select(KalshiMarket.result).where(KalshiMarket.ticker == market_ticker)
        ).scalar_one_or_none()
        if not row:
            return None
        return row.lower() if row.lower() in ("yes", "no") else None

    return _source


__all__ = [
    "PredictionPaperAdapter",
    "PredictionQuote",
    "StrategyContextBuilder",
    "StrategyFn",
    "StrategySignal",
    "db_settlement_source",
    "hold_strategy",
    "kalshi_public_quote_source",
    "registry_quote_source",
]
