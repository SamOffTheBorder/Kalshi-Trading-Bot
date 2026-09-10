"""Kalshi crypto-perpetual capture: funding, estimates, and mark snapshots.

The perp validation path (``backtest/perp_ledger.py`` §5.1) needs two series
per market that the binary-event capture does not provide:

* **funding rate history** — the realized 8-hourly settlements. Kalshi serves
  these (``/margin/funding_rates/historical``), so ``backfill_funding`` is a
  one-shot idempotent pull, not a poll.
* **mark price** — Kalshi publishes no historical mark series, so the only way
  to build one is ``poll_perp_marks``: a foreground loop over
  ``/margin/markets`` with the same causal-timestamp and honest-gap discipline
  as the BRTI capture. It never schedules itself and never runs unattended;
  ``scripts/capture_session.py --poll-perp-marks`` / ``--backfill-funding``
  are the only entry points.

Both use authenticated **read-only** ``/margin/*`` GET calls and place nothing.
"""

from __future__ import annotations

from kalshi_bot.data.perps.funding import (
    FundingBackfillResult,
    FundingEstimateCaptureResult,
    backfill_funding,
    capture_funding_estimates,
    resolve_crypto_perp_tickers,
)
from kalshi_bot.data.perps.kalshi_source import (
    KalshiPerpMarkSource,
    parse_margin_market,
)
from kalshi_bot.data.perps.mark_poll import (
    CallablePerpMarkSource,
    MarkPollResult,
    PerpMarkReadingRaw,
    PerpMarkSource,
    poll_perp_marks,
)

__all__ = [
    "CallablePerpMarkSource",
    "FundingBackfillResult",
    "FundingEstimateCaptureResult",
    "KalshiPerpMarkSource",
    "MarkPollResult",
    "PerpMarkReadingRaw",
    "PerpMarkSource",
    "backfill_funding",
    "capture_funding_estimates",
    "parse_margin_market",
    "poll_perp_marks",
    "resolve_crypto_perp_tickers",
]
