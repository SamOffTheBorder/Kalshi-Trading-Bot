"""Measure a synthetic BRTI reconstruction's error against captured BRTI.

Design decision D4 (brti-constituent-history): the number that matters is
`resolution_agreement`, not tick-level price correlation. A proxy can track
the index level within a few dollars and still disagree on outcome whenever
the two 60-second window means are close -- exactly the population KXBTC15M
contracts live in. This module measures both, but treats level error as a
sanity check and resolution agreement as the real validation signal.

Measurement only happens where captured and reconstructed coverage overlap.
No overlap means `unmeasured` -- never a fabricated or assumed-good result.
"""

from __future__ import annotations

from dataclasses import dataclass

from kalshi_bot.signals.settlement_window import (
    DEFAULT_WINDOW_SECONDS,
    BRTIReading,
    window_average,
)

UNMEASURED = "unmeasured"
MEASURED = "measured"


@dataclass(frozen=True)
class IndexPoint:
    observed_at: int  # epoch seconds
    value: float


@dataclass(frozen=True)
class ReconstructionErrorReport:
    status: str  # "measured" | "unmeasured"
    mean_abs_diff: float | None = None
    max_abs_diff: float | None = None
    resolution_agreement: float | None = None
    contracts_evaluated: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "mean_abs_diff": self.mean_abs_diff,
            "max_abs_diff": self.max_abs_diff,
            "resolution_agreement": self.resolution_agreement,
            "contracts_evaluated": self.contracts_evaluated,
        }


def _overlap_seconds(
    captured: tuple[IndexPoint, ...], reconstructed: tuple[IndexPoint, ...]
) -> tuple[dict[int, float], dict[int, float]]:
    captured_by_second = {p.observed_at: p.value for p in captured}
    reconstructed_by_second = {p.observed_at: p.value for p in reconstructed}
    common = set(captured_by_second) & set(reconstructed_by_second)
    return (
        {t: captured_by_second[t] for t in common},
        {t: reconstructed_by_second[t] for t in common},
    )


def level_error(
    captured: tuple[IndexPoint, ...], reconstructed: tuple[IndexPoint, ...]
) -> tuple[float, float] | None:
    """(mean_abs_diff, max_abs_diff) over the overlap, or None if empty."""
    cap, rec = _overlap_seconds(captured, reconstructed)
    if not cap:
        return None
    diffs = [abs(cap[t] - rec[t]) for t in cap]
    return sum(diffs) / len(diffs), max(diffs)


def resolution_agreement(
    captured: tuple[IndexPoint, ...],
    reconstructed: tuple[IndexPoint, ...],
    *,
    contract_windows: tuple[tuple[int, int], ...],
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> tuple[float, int] | None:
    """Fraction of `contract_windows` (open_ts, close_ts) where captured and
    reconstructed series agree on the KXBTC15M YES/NO outcome, using the
    contract's own resolution rule (`signals.settlement_window`). Returns
    None if no window can be evaluated from either series (no reference or
    close average on one side)."""

    captured_readings = [BRTIReading(observed_at=p.observed_at, value=p.value) for p in captured]
    reconstructed_readings = [
        BRTIReading(observed_at=p.observed_at, value=p.value) for p in reconstructed
    ]

    agreements = 0
    evaluated = 0
    for open_ts, close_ts in contract_windows:
        cap_ref = window_average(captured_readings, open_ts, window_seconds=window_seconds)
        cap_close = window_average(captured_readings, close_ts, window_seconds=window_seconds)
        rec_ref = window_average(reconstructed_readings, open_ts, window_seconds=window_seconds)
        rec_close = window_average(reconstructed_readings, close_ts, window_seconds=window_seconds)
        if None in (cap_ref, cap_close, rec_ref, rec_close):
            continue
        evaluated += 1
        cap_outcome = cap_close >= cap_ref
        rec_outcome = rec_close >= rec_ref
        if cap_outcome == rec_outcome:
            agreements += 1
    if evaluated == 0:
        return None
    return agreements / evaluated, evaluated


def measure_reconstruction_error(
    captured: tuple[IndexPoint, ...],
    reconstructed: tuple[IndexPoint, ...],
    *,
    contract_windows: tuple[tuple[int, int], ...],
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> ReconstructionErrorReport:
    """The full report: level error plus resolution agreement, or
    `unmeasured` if captured and reconstructed coverage never overlap.

    A report is never treated as passing quality evidence while
    `resolution_agreement` is absent -- callers must check `status`.
    """
    level = level_error(captured, reconstructed)
    if level is None:
        return ReconstructionErrorReport(status=UNMEASURED)

    agreement = resolution_agreement(
        captured, reconstructed, contract_windows=contract_windows, window_seconds=window_seconds
    )
    if agreement is None:
        return ReconstructionErrorReport(status=UNMEASURED)

    mean_abs_diff, max_abs_diff = level
    agreement_fraction, contracts_evaluated = agreement
    return ReconstructionErrorReport(
        status=MEASURED,
        mean_abs_diff=mean_abs_diff,
        max_abs_diff=max_abs_diff,
        resolution_agreement=agreement_fraction,
        contracts_evaluated=contracts_evaluated,
    )


__all__ = [
    "MEASURED",
    "UNMEASURED",
    "IndexPoint",
    "ReconstructionErrorReport",
    "level_error",
    "measure_reconstruction_error",
    "resolution_agreement",
]
