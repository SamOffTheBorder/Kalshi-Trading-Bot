"""Funding-carry classification gate (kxbtc15m-validation-rebuild §5.2,
design decision "Keep perps on an independent safety and economics track").

design.md, verbatim: "A binary contract is not accepted as a linear funding
hedge. Funding carry is disabled unless a compatible linear hedge, its
rollover cadence, fees, and residual basis risk are modeled and pass the
independent gate."

The v2 `strategy/funding_carry.py` prototype hedged the perp leg with a
near-the-money KXBTC *event contract*. That is exactly the thing this gate
forbids: an event contract's payoff is a step function of the settlement
index, not a linear function of the mark, so it does not neutralise a perp's
directional exposure except instantaneously and only near 50c. A position
built that way is a directional bet with a funding kicker, NOT market-
neutral carry, and must not be labelled or promoted as carry.

`classify_funding_carry` is a pure predicate. It returns `DISABLED` (with
the specific reasons) whenever:
  - the hedge instrument is a binary / event contract, or anything other
    than a genuinely linear instrument (spot, a dated future, or another
    perp on the same index), OR
  - any of the required model components is absent: the hedge's rollover /
    rebalance cadence, the full fee schedule for BOTH legs, the funding
    accrual model, and an explicit residual basis-risk estimate.

Only when every component is present AND the hedge is linear does it return
`ELIGIBLE` — and even then, promotion still requires the independent perp
gate (`backtest/perp_ledger.evaluate_perp_promotion`) to pass on real
results. This gate is necessary, not sufficient.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

LinearHedgeKind = Literal["spot", "dated_future", "perp"]
NonLinearHedgeKind = Literal["binary_event_contract", "option", "other"]


class CarryClassification(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class HedgeSpec:
    """Describes the instrument proposed to hedge a funding-carry perp leg,
    and whether each modelling component the gate requires has been
    supplied."""

    kind: LinearHedgeKind | NonLinearHedgeKind
    same_reference_index: bool
    """Does the hedge track the SAME index as the perp (BRTI for BTC)? A
    hedge on a different index carries uncontrolled basis risk."""

    rebalance_cadence_modeled: bool
    """Is the hedge's rollover / rebalance schedule and its cost modelled?
    A dated future must be rolled; a spot hedge's financing must be
    accounted; a perp hedge has its own funding."""
    both_leg_fees_modeled: bool
    """Full fee schedule for the perp leg AND the hedge leg — entry, exit,
    and any rollover fees."""
    funding_accrual_modeled: bool
    """The funding the carry actually collects, accrued per interval, not a
    single point estimate."""
    residual_basis_risk_estimated: bool
    """An explicit estimate of the tracking error that remains AFTER the
    hedge — a carry strategy with unquantified residual risk is not
    market-neutral, it just looks like it."""


@dataclass(frozen=True)
class CarryClassificationResult:
    classification: CarryClassification
    reasons: tuple[str, ...] = ()

    @property
    def eligible(self) -> bool:
        return self.classification is CarryClassification.ELIGIBLE

    def to_dict(self) -> dict[str, object]:
        return {"classification": self.classification.value, "reasons": list(self.reasons)}


_LINEAR_KINDS: frozenset[str] = frozenset({"spot", "dated_future", "perp"})


def classify_funding_carry(hedge: HedgeSpec) -> CarryClassificationResult:
    """Pure gate. `ELIGIBLE` only if the hedge is linear, on the same index,
    and every required model component is present; `DISABLED` with reasons
    otherwise."""
    reasons: list[str] = []

    if hedge.kind not in _LINEAR_KINDS:
        reasons.append(
            f"hedge kind '{hedge.kind}' is not a linear instrument "
            "(a binary event contract is never a linear funding hedge)"
        )
    if not hedge.same_reference_index:
        reasons.append("hedge does not track the same reference index as the perp leg")
    if not hedge.rebalance_cadence_modeled:
        reasons.append("hedge rollover / rebalance cadence and its cost are not modelled")
    if not hedge.both_leg_fees_modeled:
        reasons.append("full fee schedule for both legs is not modelled")
    if not hedge.funding_accrual_modeled:
        reasons.append("funding accrual is a point estimate, not modelled per interval")
    if not hedge.residual_basis_risk_estimated:
        reasons.append("residual basis risk after the hedge is not estimated")

    if reasons:
        return CarryClassificationResult(CarryClassification.DISABLED, tuple(reasons))
    return CarryClassificationResult(CarryClassification.ELIGIBLE, ())


# The classification for the v2 prototype's approach, stated once so callers
# and tests can reference it rather than re-deriving it.
BINARY_EVENT_HEDGE = HedgeSpec(
    kind="binary_event_contract",
    same_reference_index=True,  # KXBTC does track BRTI — but that isn't enough
    rebalance_cadence_modeled=False,
    both_leg_fees_modeled=True,  # funding_carry.py does model both legs' fees
    funding_accrual_modeled=False,
    residual_basis_risk_estimated=False,
)
"""What `strategy/funding_carry.py` currently assumes. `classify_funding_carry
(BINARY_EVENT_HEDGE)` is `DISABLED` — the strategy stays research-only until a
real linear hedge is specified and modelled."""


__all__ = [
    "BINARY_EVENT_HEDGE",
    "CarryClassification",
    "CarryClassificationResult",
    "HedgeSpec",
    "classify_funding_carry",
]
