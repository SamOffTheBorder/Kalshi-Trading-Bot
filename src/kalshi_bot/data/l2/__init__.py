"""Kalshi L2 order-book capture: foreground polling with causal timestamps.

The ``microprice`` experiment (``strategy/experiments.py``) needs L2 depth
that binary-event candle capture does not provide. Kalshi publishes no
historical order-book series, so the only way to build one is
``poll_l2``: a foreground loop over ``/markets/{ticker}/orderbook`` with the
same causal-timestamp and honest-gap discipline as the BRTI and perp-mark
capture. It never schedules itself and never runs unattended;
``scripts/capture_session.py --poll-l2`` is the only entry point.

Read-only, unauthenticated: no ``/orders`` path is touched and no API key is
required.
"""

from __future__ import annotations

from kalshi_bot.data.l2.kalshi_source import (
    DEFAULT_REDISCOVER_EVERY_S,
    KalshiL2Source,
    parse_orderbook,
)
from kalshi_bot.data.l2.poll import (
    CallableL2Source,
    L2PollResult,
    L2ReadingRaw,
    L2Source,
    poll_l2,
)

__all__ = [
    "DEFAULT_REDISCOVER_EVERY_S",
    "CallableL2Source",
    "KalshiL2Source",
    "L2PollResult",
    "L2ReadingRaw",
    "L2Source",
    "parse_orderbook",
    "poll_l2",
]
