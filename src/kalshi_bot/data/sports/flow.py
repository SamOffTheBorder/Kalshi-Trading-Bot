"""Anonymous, point-in-time sports market-flow research features.

The module deliberately has no strategy or broker dependency.  It accepts
captured ORM rows or plain mappings so the same calculations are replayable
from fixtures and a SQLite session.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from kalshi_bot.storage import SportsFlowFeature

FEATURE_VERSION = "sports-flow-v1"


def _get(row: Any, name: str, default: Any = None) -> Any:
    return row.get(name, default) if isinstance(row, Mapping) else getattr(row, name, default)


def _levels(raw: Any) -> list[tuple[float, float]]:
    if isinstance(raw, Mapping):
        raw = raw.get("levels") or raw.get("yes") or raw.get("bids") or raw.get("asks") or []
    result: list[tuple[float, float]] = []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return result
    for item in raw:
        if isinstance(item, Mapping):
            price = item.get("price_cents", item.get("price", item.get("yes_price")))
            size = item.get("quantity", item.get("quantity_fp", item.get("size", 0)))
        elif isinstance(item, Sequence) and len(item) >= 2:
            price, size = item[0], item[1]
        else:
            continue
        try:
            price_f = float(price)
            # Captures normally store cents; accept decimal dollars in fixtures.
            if isinstance(price, str) and "." in price and price_f <= 1:
                price_f *= 100
            result.append((price_f, float(size)))
        except (TypeError, ValueError):
            continue
    return result


def _book(row: Any) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    bids = _levels(_get(row, "bids", _get(row, "yes", _get(row, "yes_dollars", []))))
    asks = _levels(_get(row, "asks", _get(row, "no", _get(row, "no_dollars", []))))
    return bids, asks


def _mid_spread_depth(row: Any) -> tuple[float | None, float | None, float, float]:
    bids, asks = _book(row)
    bid = max((p for p, _ in bids), default=None)
    ask = min((p for p, _ in asks), default=None)
    bid_depth = sum(q for _, q in bids)
    ask_depth = sum(q for _, q in asks)
    mid = (bid + ask) / 2 if bid is not None and ask is not None else None
    spread = ask - bid if bid is not None and ask is not None else None
    return mid, spread, bid_depth, ask_depth


def copy_trading_status(*, has_attributable_identity: bool = False) -> dict[str, Any]:
    """Return the explicit product boundary for identity-based copying."""
    if has_attributable_identity:
        return {"supported": False, "status": "requires_approved_venue_adapter"}
    return {
        "supported": False,
        "status": "copy_trading_unsupported",
        "reason": "Kalshi public trades expose no trader identity",
        "alternative": "anonymous_flow_research",
    }


@dataclass(frozen=True)
class FlowFeatureWindow:
    market_ticker: str
    window_start_ts: int
    window_end_ts: int
    observed_at: int
    available_at: int
    feature_version: str
    feature_window_hash: str
    features: dict[str, float | int | str | None]
    identity_status: str = "unavailable"

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__}


def calculate_flow_features(
    trades: Iterable[Any],
    books: Iterable[Any],
    *,
    market_ticker: str | None = None,
    decision_ts: int | None = None,
    window_s: int = 300,
    response_horizon_s: int = 60,
) -> FlowFeatureWindow:
    """Calculate features using only rows observable by ``decision_ts``.

    ``post_flow_response`` is a target label, not an input: it is computed
    only when a later book is supplied and is never used in the feature hash.
    """
    trade_rows = list(trades)
    book_rows = list(books)
    if decision_ts is None:
        decision_ts = max([_get(r, "observed_at", 0) for r in trade_rows + book_rows] or [0])
    start = int(decision_ts - window_s)
    eligible_trades = [
        r
        for r in trade_rows
        if start <= int(_get(r, "observed_at", 0)) <= decision_ts
        and int(_get(r, "available_at", 0)) <= decision_ts
        and (market_ticker is None or _get(r, "market_ticker") == market_ticker)
    ]
    seen: set[str] = set()
    unique_trades: list[Any] = []
    for row in sorted(eligible_trades, key=lambda r: (_get(r, "observed_at", 0), _get(r, "id", 0))):
        raw_id = _get(row, "trade_id")
        key = (
            str(raw_id)
            if raw_id
            else (
                f"{_get(row, 'observed_at')}|{_get(row, 'price_cents')}|"
                f"{_get(row, 'quantity')}|{_get(row, 'taker_side')}"
            )
        )
        if key in seen:
            continue
        seen.add(key)
        unique_trades.append(row)
    signed = 0.0
    signed_notional = 0.0
    notional = 0.0
    buy_qty = sell_qty = 0.0
    for row in unique_trades:
        qty = float(_get(row, "quantity", _get(row, "quantity_fp", 0)) or 0)
        price = float(_get(row, "price_cents", _get(row, "price", 0)) or 0)
        side = str(_get(row, "taker_side", "")).lower()
        sign = (
            1.0 if side in {"yes", "buy", "bid"} else -1.0 if side in {"no", "sell", "ask"} else 0.0
        )
        signed += sign * qty
        signed_notional += sign * qty * price
        notional += qty * price
        buy_qty += qty if sign > 0 else 0
        sell_qty += qty if sign < 0 else 0
    total_qty = buy_qty + sell_qty
    trade_imbalance = signed / total_qty if total_qty else 0.0
    causal_books = [
        r
        for r in book_rows
        if start <= int(_get(r, "observed_at", 0)) <= decision_ts
        and int(_get(r, "available_at", 0)) <= decision_ts
        and (market_ticker is None or _get(r, "market_ticker") == market_ticker)
    ]
    causal_books.sort(key=lambda r: _get(r, "observed_at", 0))
    latest = causal_books[-1] if causal_books else None
    previous = causal_books[-2] if len(causal_books) > 1 else None
    mid, spread, bid_depth, ask_depth = (
        _mid_spread_depth(latest) if latest else (None, None, 0.0, 0.0)
    )
    _old_mid, old_spread, old_bid_depth, old_ask_depth = (
        _mid_spread_depth(previous) if previous else (None, None, 0.0, 0.0)
    )
    total_depth = bid_depth + ask_depth
    book_imbalance = (bid_depth - ask_depth) / total_depth if total_depth else 0.0
    old_total = old_bid_depth + old_ask_depth
    old_imbalance = (old_bid_depth - old_ask_depth) / old_total if old_total else 0.0
    quote_replenishment = max(0.0, (bid_depth + ask_depth) - old_total) if previous else 0.0
    future_books = [
        r
        for r in book_rows
        if decision_ts < int(_get(r, "observed_at", 0)) <= decision_ts + response_horizon_s
        and int(_get(r, "available_at", 0)) >= int(_get(r, "observed_at", 0))
        and (market_ticker is None or _get(r, "market_ticker") == market_ticker)
    ]
    future_mid = (
        _mid_spread_depth(sorted(future_books, key=lambda r: _get(r, "observed_at", 0))[-1])[0]
        if future_books
        else None
    )
    response = future_mid - mid if future_mid is not None and mid is not None else None
    observed_at = max(
        [int(_get(r, "observed_at", 0)) for r in unique_trades + causal_books] or [decision_ts]
    )
    available_at = max(
        [int(_get(r, "available_at", 0)) for r in unique_trades + causal_books] or [decision_ts]
    )
    material = {
        "market_ticker": market_ticker
        or _get(latest or unique_trades[0] if unique_trades else {}, "market_ticker", ""),
        "start": start,
        "end": decision_ts,
        "trade_ids": sorted(seen),
        "book_observed_at": [int(_get(r, "observed_at", 0)) for r in causal_books],
    }
    digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    features: dict[str, float | int | str | None] = {
        "trade_count": len(unique_trades),
        "signed_trade_imbalance": trade_imbalance,
        "signed_notional_flow": signed_notional,
        "notional_flow": notional,
        "book_imbalance": book_imbalance,
        "book_imbalance_change": book_imbalance - old_imbalance,
        "quote_replenishment": quote_replenishment,
        "spread_cents": spread,
        "spread_change_cents": spread - old_spread
        if spread is not None and old_spread is not None
        else None,
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
        "depth_change": total_depth - old_total,
        "post_flow_response_cents": response,
        "copy_trading": "copy_trading_unsupported",
    }
    return FlowFeatureWindow(
        market_ticker or str(material["market_ticker"]),
        start,
        int(decision_ts),
        observed_at,
        available_at,
        FEATURE_VERSION,
        digest,
        features,
    )


def persist_flow_feature(
    session: Session,
    feature: FlowFeatureWindow,
    *,
    series_ticker: str,
    capture_session_id: str | None = None,
) -> SportsFlowFeature:
    row = SportsFlowFeature(
        series_ticker=series_ticker,
        market_ticker=feature.market_ticker,
        window_start_ts=feature.window_start_ts,
        window_end_ts=feature.window_end_ts,
        observed_at=feature.observed_at,
        available_at=feature.available_at,
        feature_version=feature.feature_version,
        feature_window_hash=feature.feature_window_hash,
        features=feature.features,
        identity_status=feature.identity_status,
        capture_session_id=capture_session_id,
        provenance={"causal": True},
    )
    session.add(row)
    session.flush()
    return row


__all__ = [
    "FEATURE_VERSION",
    "FlowFeatureWindow",
    "calculate_flow_features",
    "copy_trading_status",
    "persist_flow_feature",
]
