"""Market liveness filter (spec: backtest-engine "Only live markets are
tradeable"; kalshi-market-data "Market liveness is recorded").

92 of 100 sampled `KXBTCD` strikes (2026-09-01/09-04) were 0c/1c shells with
zero open interest — quotes with no real market behind them. Phase 1's
backtest filled against these phantom quotes, which is where its apparent
profit came from. This is the mandatory guard: a candle without a genuine
two-sided quote AND non-zero open interest is not tradeable, full stop.
"""

from __future__ import annotations

from kalshi_bot.storage.models import Candle


def is_live_quote(candle: Candle) -> bool:
    """True iff `candle` had a two-sided quote and non-zero open interest.

    Two-sided: both `yes_bid_close` and `yes_ask_close` present (not None)
    and within the valid 1-99c range — a quote of 0c or 100c on either side
    is degenerate, not a real two-sided market.
    """
    if candle.open_interest <= 0:
        return False
    bid, ask = candle.yes_bid_close, candle.yes_ask_close
    if bid is None or ask is None:
        return False
    return 1 <= bid <= 99 and 1 <= ask <= 99
