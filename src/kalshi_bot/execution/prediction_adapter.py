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
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.config.crypto_registry import (
    DEFAULT_CRYPTO_REGISTRY,
    CryptoAssetConfig,
)
from kalshi_bot.config.lifecycle import Domain
from kalshi_bot.execution.broker_protocol import MarketSnapshot, OrderRequest
from kalshi_bot.execution.orchestrator import AdapterDecision, ReconciliationOutcome
from kalshi_bot.execution.paper_broker import PaperBroker
from kalshi_bot.storage.models import KalshiMarket, SimulatedTrade


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


# A strategy here is any callable that turns a quote into a decision.
# It returns (action, side, limit_price_cents, meta) where action is one of
# "hold" | "buy". This keeps the adapter independent of any concrete
# strategy class while the change's strategy selection is still open.
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


@dataclass
class PredictionPaperAdapter:
    """Shared-envelope wrapper over `PaperBroker` for one paper run."""

    session: Session
    quote_source: Callable[[str, int], PredictionQuote | None]
    settlement_source: Callable[[str], str | None]
    starting_cash_usd: float
    strategy: StrategyFn = hold_strategy
    registry: Sequence[CryptoAssetConfig] = DEFAULT_CRYPTO_REGISTRY
    max_data_age_seconds: int = 120

    domain: Domain = "prediction"
    broker_name: str = "paper"

    _broker: PaperBroker = field(init=False)
    _open_by_asset: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._broker = PaperBroker(self.session, starting_cash_usd=self.starting_cash_usd)
        # Map restored open positions back to their asset via the registry.
        for ticker in self._broker.open_position_tickers():
            asset = self._asset_for_ticker(ticker)
            if asset is not None:
                self._open_by_asset[asset] = ticker

    # -- registry resolution -------------------------------------------

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

    # -- DomainPaperAdapter --------------------------------------------

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

        signal = self.strategy(quote)
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

    # -- helpers ------------------------------------------------------

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
    "StrategyFn",
    "StrategySignal",
    "db_settlement_source",
    "hold_strategy",
    "kalshi_public_quote_source",
    "registry_quote_source",
]
