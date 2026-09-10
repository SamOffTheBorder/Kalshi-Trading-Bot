"""Public, read-only sports market discovery."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from kalshi_bot.data.kalshi.parse import dollars_to_cents, iso_to_ts
from kalshi_bot.data.sports.classifier import Classification, RejectionReason, classify_market
from kalshi_bot.storage import SportsMarketDiscovery, SportsMarketRuleProvenance, SportsSeries


def _now() -> int:
    return int(time.time())


def _number(raw: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if raw.get(key) is not None:
            try:
                return float(raw[key])
            except (TypeError, ValueError):
                return None
    return None


def _price(raw: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        if raw.get(key) is not None:
            return (
                dollars_to_cents(str(raw[key]))
                if isinstance(raw[key], str) and "." in str(raw[key])
                else int(raw[key])
            )
    return None


@dataclass(frozen=True)
class DiscoveryConfig:
    min_open_interest: float = 1.0
    min_top_size: float = 1.0
    max_spread_cents: int = 20


@dataclass(frozen=True)
class DiscoveryRow:
    series_ticker: str
    market_ticker: str
    classification: Classification
    observed_at: int
    yes_bid_cents: int | None
    yes_ask_cents: int | None
    bid_size: float | None
    ask_size: float | None
    open_interest: float | None
    volume: float | None
    close_ts: int | None
    raw: dict[str, Any]

    @property
    def spread_cents(self) -> int | None:
        if self.yes_bid_cents is None or self.yes_ask_cents is None:
            return None
        return self.yes_ask_cents - self.yes_bid_cents


def _rule_hash(raw: dict[str, Any]) -> str:
    fields = {
        k: raw.get(k)
        for k in (
            "rules_primary",
            "rules_secondary",
            "settlement_source",
            "settlement_source_url",
            "outcomes",
            "outcome_shape",
        )
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True, default=str).encode()).hexdigest()


class SportsDiscovery:
    def __init__(self, client: Any, *, config: DiscoveryConfig | None = None, clock=_now) -> None:
        self.client = client
        self.config = config or DiscoveryConfig()
        self.clock = clock

    def evaluate(
        self, series: dict[str, Any], market: dict[str, Any], *, observed_at: int | None = None
    ) -> DiscoveryRow:
        now = int(self.clock() if observed_at is None else observed_at)
        classification = classify_market(market, series=series)
        # Kalshi's current market payload quotes prices as `*_dollars` strings
        # and sizes as `*_size_fp`. The older cent/size keys are kept as
        # fallbacks so archived payloads still parse.
        bid = _price(market, "yes_bid_dollars", "yes_bid", "yes_bid_cents")
        ask = _price(market, "yes_ask_dollars", "yes_ask", "yes_ask_cents")
        bid_size = _number(
            market, "yes_bid_size_fp", "yes_bid_size", "yes_bid_fp", "bid_size", "top_bid_size"
        )
        ask_size = _number(
            market, "yes_ask_size_fp", "yes_ask_size", "yes_ask_fp", "ask_size", "top_ask_size"
        )
        oi = _number(market, "open_interest_fp", "open_interest")
        volume = _number(market, "volume_fp", "volume")
        row = DiscoveryRow(
            str(series.get("ticker") or market.get("series_ticker") or ""),
            str(market.get("ticker") or ""),
            classification,
            now,
            bid,
            ask,
            bid_size,
            ask_size,
            oi,
            volume,
            iso_to_ts(market["close_time"]) if market.get("close_time") else None,
            market,
        )
        reason = row.classification.reason
        if row.classification.eligible and (bid is None or ask is None or bid >= ask):
            reason = RejectionReason.NOT_LIQUID
        if row.classification.eligible and (
            row.spread_cents is None or row.spread_cents > self.config.max_spread_cents
        ):
            reason = RejectionReason.NOT_LIQUID
        if row.classification.eligible and (
            (bid_size or 0) < self.config.min_top_size or (ask_size or 0) < self.config.min_top_size
        ):
            reason = RejectionReason.NOT_LIQUID
        if row.classification.eligible and (oi or 0) < self.config.min_open_interest:
            reason = RejectionReason.NOT_LIQUID
        if reason:
            row = DiscoveryRow(
                row.series_ticker,
                row.market_ticker,
                Classification(
                    False,
                    row.classification.outcome_shape,
                    row.classification.sport,
                    str(reason),
                    row.classification.settlement_source,
                ),
                row.observed_at,
                row.yes_bid_cents,
                row.yes_ask_cents,
                row.bid_size,
                row.ask_size,
                row.open_interest,
                row.volume,
                row.close_ts,
                row.raw,
            )
        return row

    def discover(
        self, session: Session, *, series_tickers: Iterable[str], session_id: str | None = None
    ) -> list[DiscoveryRow]:
        out: list[DiscoveryRow] = []
        available = int(self.clock())
        for ticker in series_tickers:
            endpoint = f"/series/{ticker}"
            series = self.client.get_series(ticker)
            series_ticker = str(series.get("ticker") or ticker)
            session.add(
                SportsSeries(
                    series_ticker=series_ticker,
                    sport=series.get("sport") or series.get("category"),
                    title=series.get("title"),
                    observed_at=available,
                    available_at=available,
                    source_endpoint=endpoint,
                    capture_session_id=session_id,
                    metadata_json=series,
                )
            )
            for market in self.client.iter_markets(series_ticker=ticker):
                row = self.evaluate(series, market)
                out.append(row)
                rules = SportsMarketRuleProvenance(
                    market_ticker=row.market_ticker,
                    observed_at=row.observed_at,
                    available_at=available,
                    content_hash=_rule_hash(market),
                    settlement_source=row.classification.settlement_source,
                    outcome_shape=row.classification.outcome_shape,
                    rules_json={
                        k: market.get(k)
                        for k in (
                            "rules_primary",
                            "rules_secondary",
                            "settlement_source",
                            "settlement_source_url",
                            "outcomes",
                            "outcome_shape",
                        )
                    },
                    source_endpoint=endpoint,
                    capture_session_id=session_id,
                )
                session.add(rules)
                session.flush()
                close = row.close_ts
                session.add(
                    SportsMarketDiscovery(
                        series_ticker=row.series_ticker,
                        market_ticker=row.market_ticker,
                        sport=row.classification.sport,
                        title=market.get("title"),
                        event_ticker=market.get("event_ticker"),
                        close_ts=close,
                        observed_at=row.observed_at,
                        available_at=available,
                        status=market.get("status"),
                        outcome_shape=row.classification.outcome_shape,
                        settlement_source=row.classification.settlement_source,
                        fee_metadata=market.get("fee_schedule") or market.get("fees"),
                        yes_bid_cents=row.yes_bid_cents,
                        yes_ask_cents=row.yes_ask_cents,
                        bid_size=row.bid_size,
                        ask_size=row.ask_size,
                        open_interest=row.open_interest,
                        volume=row.volume,
                        spread_cents=row.spread_cents,
                        eligible=row.classification.eligible,
                        failure_reason=row.classification.reason,
                        rule_provenance_id=rules.id,
                        raw_metadata=market,
                        source_endpoint=endpoint,
                        capture_session_id=session_id,
                    )
                )
        session.commit()
        return out


def discover_sports(
    session: Session,
    client: Any,
    *,
    series_tickers: Iterable[str],
    config: DiscoveryConfig | None = None,
    session_id: str | None = None,
) -> list[DiscoveryRow]:
    return SportsDiscovery(client, config=config).discover(
        session, series_tickers=series_tickers, session_id=session_id
    )
