"""Kalshi's actual fee schedule — the single source of truth for fee math.

Corrected model (v2, replacing Phase 1's `0.07 * net_winnings_at_settlement`,
which was verified wrong — see the v2-perps-scalping-and-frontend change's
design.md for the sampled facts):

    fee(P, n, coef) = ceil(coef * P * (1-P) * n * 100) / 100   dollars, TOTAL
                       for the order (n contracts, not per-contract before
                       rounding)

- Taker coefficient: 0.07
- Maker coefficient: 0.0175 (one quarter of taker)
- Charged ONCE, AT ENTRY, regardless of outcome. There is no settlement fee
  — the formula evaluates to 0 at P=0 or P=1, and Kalshi does not charge
  again when a position resolves.

`P` is the contract price in dollars (e.g. 0.42 for 42 cents). The fee peaks
at P=0.50 and is symmetric around it. Rounding is applied to the whole
order, not contract-by-contract: at small `n` this makes the effective
per-contract fee lumpier than the textbook curve (e.g. n=1 at P=0.50 taker
rounds up to 2.0c/contract, not the "typical" 1.75c) — that convergence
only shows up at realistic order sizes (see the v2 change's cost-floor.md).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

TAKER_FEE_COEFFICIENT = 0.07
MAKER_FEE_COEFFICIENT = 0.0175


@dataclass(frozen=True)
class FeeConfig:
    """Versioned exchange fee assumptions recorded with validation runs."""

    version: str = "2026-09-kalshi"
    taker_coefficient: float = TAKER_FEE_COEFFICIENT
    maker_coefficient: float = MAKER_FEE_COEFFICIENT
    charged_at_entry: bool = True
    settlement_fee: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


DEFAULT_FEE_CONFIG = FeeConfig()


@dataclass(frozen=True)
class ResolutionSpec:
    """Versioned KXBTC15M settlement predicate."""

    version: str = "2026-09-kxbtc15m-brti-60s"
    series_ticker: str = "KXBTC15M"
    window_seconds: int = 60
    tie_result: str = "yes"

    def resolves_yes(self, average_before_close: float, average_before_open: float) -> bool:
        return average_before_close >= average_before_open

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


DEFAULT_RESOLUTION_SPEC = ResolutionSpec()


def entry_fee_dollars(
    price_cents: int,
    quantity: float,
    *,
    coefficient: float = TAKER_FEE_COEFFICIENT,
) -> float:
    """Total fee (dollars) for entering `quantity` contracts at `price_cents`.

    Charged once, at entry, regardless of whether the position ultimately
    wins or loses. Zero at price_cents 0 or 100 (never actually reachable —
    contract prices are 1-99 — but the formula is well-defined there too).
    """
    if quantity <= 0:
        return 0.0
    p = price_cents / 100.0
    return math.ceil(coefficient * p * (1.0 - p) * quantity * 100) / 100.0


def entry_fee_rate_at_price(
    price_dollars: float, *, coefficient: float = TAKER_FEE_COEFFICIENT
) -> float:
    """Fee as a fraction of $1 notional per contract, ignoring order-size
    rounding (the textbook curve): coefficient * P * (1-P). Used where a
    per-contract cost-fraction is needed independent of a specific order
    size — e.g. the breakeven-win-rate formula, where the fee is added
    directly to the cost basis P."""
    return coefficient * price_dollars * (1.0 - price_dollars)
