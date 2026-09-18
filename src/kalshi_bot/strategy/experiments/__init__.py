"""Separately-labelled short-horizon experiments (kxbtc15m-validation-rebuild
§4.5).

design.md is explicit that microprice, public-trade imbalance, and
quarter-hour opening effects enter "as candidate features or separately
reported experiments" — NOT as presumed edges — and that each is deferred
"when the required data coverage is insufficient".

As of this change none of the three has usable data:

- **microprice** needs L2 order-book snapshots (`storage.models.
  OrderBookSnapshot`, added by §1.3) — none captured yet.
- **public-trade imbalance** needs `storage.models.PublicTrade` rows — none
  captured yet.
- **quarter-hour opening effect** needs many KXBTC15M windows with dense
  BRTI coverage right at the open; the archived BRTI series does not yet
  reach that density.

So each experiment is a documented feature builder guarded by an
`available()` check that returns False until its data exists. The
walk-forward report (§3.4 / §4.6) calls `available()` and records the
experiment as DEFERRED rather than running it on absent data. When capture
sessions (`scripts/capture_session.py`, §1.4) accumulate the inputs, the
builders here get filled in and flip to available.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExperimentStatus:
    name: str
    available: bool
    reason: str
    """Why it is or isn't runnable — the string the report prints next to
    a DEFERRED experiment so the deferral is never silent."""


MICROPRICE = ExperimentStatus(
    name="microprice",
    available=False,
    reason=(
        "no OrderBookSnapshot (L2) rows captured yet "
        "(needs scripts/capture_session.py L2 import)"
    ),
)

TRADE_IMBALANCE = ExperimentStatus(
    name="public_trade_imbalance",
    available=False,
    reason="no PublicTrade rows captured yet (needs scripts/capture_session.py trade import)",
)

QUARTER_HOUR_OPEN = ExperimentStatus(
    name="quarter_hour_open_effect",
    available=False,
    reason="archived BRTI series is not dense enough at KXBTC15M window opens",
)

ALL_EXPERIMENTS: tuple[ExperimentStatus, ...] = (
    MICROPRICE,
    TRADE_IMBALANCE,
    QUARTER_HOUR_OPEN,
)


def deferred_experiments() -> tuple[ExperimentStatus, ...]:
    """The experiments that cannot run yet — for the walk-forward report to
    list explicitly (§4.5: defer, don't silently skip)."""
    return tuple(e for e in ALL_EXPERIMENTS if not e.available)


__all__ = [
    "ALL_EXPERIMENTS",
    "MICROPRICE",
    "QUARTER_HOUR_OPEN",
    "TRADE_IMBALANCE",
    "ExperimentStatus",
    "deferred_experiments",
]
