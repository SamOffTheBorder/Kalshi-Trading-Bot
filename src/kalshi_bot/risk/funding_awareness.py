"""Funding-rate awareness for open perps positions (tasks.md 5.5, spec:
perps-trading "Funding-rate awareness").

Surfaces, for any open perps position: the next funding timestamp, the
current funding-rate estimate, and whether that position currently pays or
receives funding — sourced from `KalshiMarginClient.get_funding_rate_estimate`
(response fields verified against `docs.kalshi.com/margin-rest/funding/
get-funding-rate-estimate.md` 2026-09-06: `market_ticker`, `computed_time`,
`funding_rate`, `mark_price`, `next_funding_time`).

**Sign-convention caveat — assumption, not verified fact:** Kalshi's
published docs describe `funding_rate` ("time-weighted average of the
premium index over `[last_funding_time, now)`") but do not state which side
pays when the rate is positive, nor the exact payment formula. This module
assumes the convention used by essentially every other perpetual-futures
venue (Binance, dYdX, etc.): **positive funding_rate means longs pay
shorts**, and the payment owed is `position_notional_usd * funding_rate`
(sign-adjusted for side). This assumption should be confirmed against a
real observed funding payment (via `get_funding_history`, tasks.md 4.4)
before this module's `payment` figures are trusted for anything beyond
directional awareness — treat `pays_or_receives` as higher-confidence than
the exact `estimated_payment_usd` number until then.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

Side = Literal["long", "short"]
PayOrReceive = Literal["pays", "receives", "flat"]


@dataclass(frozen=True)
class FundingState:
    market_ticker: str
    next_funding_time: datetime
    funding_rate: float
    mark_price: float
    side: Side
    pays_or_receives: PayOrReceive
    estimated_payment_usd: float
    """Positive = this position pays this amount at the next funding event;
    negative = it receives |this amount|. See module docstring: the sign
    convention producing this number is an unverified assumption."""


def funding_state_from_estimate(
    estimate_response: dict[str, object],
    *,
    side: Side,
    position_notional_usd: float,
) -> FundingState:
    """Build a `FundingState` from `KalshiMarginClient.get_funding_rate_estimate()`'s
    raw response dict for one open position.

    `position_notional_usd` should already reflect the position's sign
    conceptually (it's always given as a magnitude here; `side` carries the
    direction) — pass `abs(position_notional)`.
    """
    funding_rate = float(estimate_response["funding_rate"])  # type: ignore[arg-type]
    mark_price = float(Decimal(str(estimate_response["mark_price"])))
    next_funding_time = _parse_datetime(estimate_response["next_funding_time"])

    # Assumed convention (see module docstring): positive rate -> longs pay
    # shorts. A long's payment is +notional*rate (pays when rate > 0); a
    # short's is the mirror image.
    signed_payment = position_notional_usd * funding_rate
    if side == "short":
        signed_payment = -signed_payment

    if signed_payment > 0:
        pays_or_receives: PayOrReceive = "pays"
    elif signed_payment < 0:
        pays_or_receives = "receives"
    else:
        pays_or_receives = "flat"

    return FundingState(
        market_ticker=str(estimate_response["market_ticker"]),
        next_funding_time=next_funding_time,
        funding_rate=funding_rate,
        mark_price=mark_price,
        side=side,
        pays_or_receives=pays_or_receives,
        estimated_payment_usd=signed_payment,
    )


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value)
    # RFC3339 "Z" suffix isn't accepted by fromisoformat on Python < 3.11's
    # backport paths in all cases; normalize defensively.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


__all__ = ["FundingState", "PayOrReceive", "Side", "funding_state_from_estimate"]
