"""Foreground-only, read-only sports capture."""

from __future__ import annotations

import itertools
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.data.kalshi.parse import dollars_to_cents
from kalshi_bot.storage import (
    SportsCandle,
    SportsCaptureGap,
    SportsMarketDiscovery,
    SportsOrderBookSnapshot,
    SportsPublicTrade,
)


def _ts(raw: dict[str, Any], fallback: int) -> int:
    for key in ("observed_at", "timestamp", "ts", "time", "created_time", "trade_time"):
        value = raw.get(key)
        if value is None:
            continue
        try:
            number = float(value)
            return int(number / 1000) if number > 10_000_000_000 else int(number)
        except (TypeError, ValueError):
            continue
    return fallback


def _cents(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and "." in value:
        return dollars_to_cents(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _top(levels: Any) -> tuple[int | None, float | None]:
    if not isinstance(levels, list) or not levels:
        return None, None
    first = levels[0]
    if isinstance(first, dict):
        return _cents(
            first.get("price") or first.get("price_cents") or first.get("yes_price")
        ), float(first.get("quantity") or first.get("quantity_fp") or first.get("size") or 0)
    if isinstance(first, (list, tuple)) and first:
        return _cents(first[0]), float(first[1]) if len(first) > 1 else None
    return None, None


@dataclass(frozen=True)
class CaptureResult:
    session_id: str
    markets: int = 0
    candles: int = 0
    order_books: int = 0
    trades: int = 0
    gaps: int = 0
    errors: tuple[str, ...] = ()


def _capture_candles(
    session: Session,
    client: Any,
    discovery: SportsMarketDiscovery,
    *,
    start_ts: int,
    end_ts: int,
    period_minutes: int,
    session_id: str,
    available_at: int,
) -> int:
    raw_items = client.get_candlesticks(
        discovery.series_ticker,
        discovery.market_ticker,
        start_ts=start_ts,
        end_ts=end_ts,
        period_minutes=period_minutes,
    )
    count = 0
    for raw in raw_items:
        end = int(raw["end_period_ts"])
        bid = raw.get("yes_bid") or {}
        ask = raw.get("yes_ask") or {}
        session.merge(
            SportsCandle(
                series_ticker=discovery.series_ticker,
                market_ticker=discovery.market_ticker,
                period_minutes=period_minutes,
                end_period_ts=end,
                observed_at=end - period_minutes * 60,
                available_at=available_at,
                yes_bid_cents=_cents(
                    bid.get("close") or bid.get("close_cents") or bid.get("close_dollars")
                ),
                yes_ask_cents=_cents(
                    ask.get("close") or ask.get("close_cents") or ask.get("close_dollars")
                ),
                volume=float(raw.get("volume_fp") or raw.get("volume") or 0),
                open_interest=float(raw.get("open_interest_fp") or raw.get("open_interest") or 0),
                source_endpoint=f"/series/{discovery.series_ticker}/markets/{discovery.market_ticker}/candlesticks",
                capture_session_id=session_id,
                provenance={"raw": raw},
            )
        )
        count += 1
    return count


def capture_sports(
    session: Session,
    client: Any,
    *,
    market_tickers: Iterable[str] | None = None,
    start_ts: int,
    end_ts: int,
    period_minutes: int = 1,
    include_order_books: bool = True,
    include_trades: bool = True,
    session_id: str | None = None,
) -> CaptureResult:
    """Capture a bounded interval for already-discovered eligible markets.

    This function is deliberately one-shot. A caller may invoke it from an
    operator-owned foreground process; it never schedules or restarts itself.
    """
    sid = session_id or f"sports-manual-{uuid.uuid4().hex}"
    wanted = set(market_tickers or ())
    rows = (
        session.execute(
            select(SportsMarketDiscovery).where(SportsMarketDiscovery.eligible.is_(True))
        )
        .scalars()
        .all()
    )
    rows = [r for r in rows if not wanted or r.market_ticker in wanted]
    now = int(time.time())
    candles = books = trades = 0
    errors: list[str] = []
    for discovery in rows:
        try:
            candles += _capture_candles(
                session,
                client,
                discovery,
                start_ts=start_ts,
                end_ts=end_ts,
                period_minutes=period_minutes,
                session_id=sid,
                available_at=now,
            )
            if include_order_books:
                raw = client.get_orderbook(discovery.market_ticker)
                book = raw.get("orderbook", raw)
                observed = _ts(book, now)
                bids = book.get("yes", book.get("bids", []))
                asks = book.get("no", book.get("asks", []))
                session.add(
                    SportsOrderBookSnapshot(
                        series_ticker=discovery.series_ticker,
                        market_ticker=discovery.market_ticker,
                        observed_at=observed,
                        available_at=now,
                        bids=bids or [],
                        asks=asks or [],
                        source_endpoint=f"/markets/{discovery.market_ticker}/orderbook",
                        capture_session_id=sid,
                        provenance={"raw": raw},
                    )
                )
                books += 1
            if include_trades:
                for raw_trade in client.iter_trades(
                    ticker=discovery.market_ticker, min_ts=start_ts, max_ts=end_ts
                ):
                    observed = _ts(raw_trade, now)
                    price = _cents(
                        raw_trade.get("price")
                        or raw_trade.get("yes_price")
                        or raw_trade.get("price_dollars")
                    )
                    if price is None:
                        continue
                    session.add(
                        SportsPublicTrade(
                            series_ticker=discovery.series_ticker,
                            market_ticker=discovery.market_ticker,
                            observed_at=observed,
                            available_at=now,
                            price_cents=price,
                            quantity=float(
                                raw_trade.get("count")
                                or raw_trade.get("quantity_fp")
                                or raw_trade.get("quantity")
                                or 0
                            ),
                            taker_side=raw_trade.get("taker_side"),
                            trade_id=raw_trade.get("trade_id"),
                            source_endpoint="/markets/trades",
                            capture_session_id=sid,
                            provenance={"raw": raw_trade},
                        )
                    )
                    trades += 1
        except Exception as exc:  # one market must not hide other coverage
            errors.append(f"{discovery.market_ticker}: {exc}")
    session.commit()
    gap_count = record_gaps(session, session_id=sid, expected_interval_s=period_minutes * 60)
    return CaptureResult(sid, len(rows), candles, books, trades, gap_count, tuple(errors))


def record_gaps(
    session: Session,
    *,
    session_id: str | None = None,
    expected_interval_s: int = 60,
    threshold: float = 1.5,
) -> int:
    """Persist/report gaps for candles, books, and trades, without filling."""
    count = 0
    for model, kind in (
        (SportsCandle, "candle"),
        (SportsOrderBookSnapshot, "order_book"),
        (SportsPublicTrade, "trade"),
    ):
        tickers = session.execute(select(model.market_ticker).distinct()).scalars().all()
        for ticker in tickers:
            if model is SportsCandle:
                values = (
                    session.execute(
                        select(model.observed_at)
                        .where(model.market_ticker == ticker)
                        .order_by(model.observed_at)
                    )
                    .scalars()
                    .all()
                )
            else:
                values = (
                    session.execute(
                        select(model.observed_at)
                        .where(model.market_ticker == ticker)
                        .order_by(model.observed_at)
                    )
                    .scalars()
                    .all()
                )
            for previous, current in itertools.pairwise(values):
                if current - previous > expected_interval_s * threshold:
                    session.add(
                        SportsCaptureGap(
                            market_ticker=ticker,
                            observation_kind=kind,
                            start_ts=previous,
                            end_ts=current,
                            expected_interval_s=expected_interval_s,
                            capture_session_id=session_id,
                            reason="capture_gap",
                        )
                    )
                    count += 1
    session.commit()
    return count


def capture_report(session: Session, *, market_ticker: str | None = None) -> dict[str, Any]:
    gaps = select(SportsCaptureGap)
    if market_ticker:
        gaps = gaps.where(SportsCaptureGap.market_ticker == market_ticker)
    rows = session.execute(gaps.order_by(SportsCaptureGap.start_ts)).scalars().all()
    return {
        "market_ticker": market_ticker,
        "gap_count": len(rows),
        "gaps": [
            {
                "kind": r.observation_kind,
                "start_ts": r.start_ts,
                "end_ts": r.end_ts,
                "expected_interval_s": r.expected_interval_s,
                "session_id": r.capture_session_id,
            }
            for r in rows
        ],
    }
