"""Kalshi public-trade capture: foreground polling with causal timestamps.

The ``public_trade_imbalance`` experiment (``strategy/experiments.py``)
needs a trade stream that binary-event candle capture does not provide.
``poll_public_trades`` is a foreground loop over ``/markets/trades`` with the
same causal-timestamp and honest-gap discipline as the BRTI, perp-mark, and
L2 capture. It never schedules itself and never runs unattended;
``scripts/capture_session.py --poll-trades`` is the only entry point.

Read-only, unauthenticated: no ``/orders`` path is touched and no API key is
required.
"""

from __future__ import annotations

from kalshi_bot.data.public_trades.kalshi_source import (
    DEFAULT_MAX_PAGES_PER_TICKER,
    DEFAULT_REDISCOVER_EVERY_S,
    KalshiTradeSource,
    parse_trade,
)
from kalshi_bot.data.public_trades.poll import (
    CallableTradeSource,
    TradePollResult,
    TradeReadingRaw,
    TradeSource,
    poll_public_trades,
)

__all__ = [
    "DEFAULT_MAX_PAGES_PER_TICKER",
    "DEFAULT_REDISCOVER_EVERY_S",
    "CallableTradeSource",
    "KalshiTradeSource",
    "TradePollResult",
    "TradeReadingRaw",
    "TradeSource",
    "parse_trade",
    "poll_public_trades",
]
