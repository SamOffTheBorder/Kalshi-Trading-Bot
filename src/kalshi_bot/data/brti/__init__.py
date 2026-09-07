"""BRTI (CF Benchmarks Bitcoin Real Time Index) capture.

KXBTC15M resolves off the BRTI, not off any exchange spot feed: YES iff the
mean BRTI over the 60 s ending at close is >= the mean over the 60 s ending
at open (ties -> YES). The validation path therefore needs a densely sampled,
causally honest BRTI history — one that records, per reading, both when the
value refers to (`observed_at`) and when a live system could first have acted
on it (`available_at`).

This package is the foreground capture machinery for that series. It never
schedules itself and never runs unattended — `scripts/capture_session.py
--poll-brti` is the only entry point, and it stops on Ctrl+C or when its
`--duration` elapses.

The concrete data source is deliberately pluggable (`BRTISource`): the choice
of endpoint (CF Benchmarks real-time API, a licensed historical export, a
Kalshi index endpoint) is an operator decision that is not yet made. The
polling loop, gap accounting, resumability and persistence do not depend on
it.
"""

from __future__ import annotations

from kalshi_bot.data.brti.poll import (
    BRTIReadingRaw,
    BRTISource,
    CallableBRTISource,
    PollResult,
    poll_brti,
)

__all__ = [
    "BRTIReadingRaw",
    "BRTISource",
    "CallableBRTISource",
    "PollResult",
    "poll_brti",
]
