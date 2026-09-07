"""Embargoed rolling walk-forward evaluation primitives."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class WalkForwardFold:
    index: int
    train_start_ts: int
    train_end_ts: int
    test_start_ts: int
    test_end_ts: int
    embargo_seconds: int


@dataclass(frozen=True)
class WalkForwardResult:
    folds: tuple[WalkForwardFold, ...]
    reports: tuple[object, ...]


def rolling_folds(
    *, start_ts: int, end_ts: int, train_seconds: int, test_seconds: int,
    embargo_seconds: int = 0, step_seconds: int | None = None,
) -> tuple[WalkForwardFold, ...]:
    """Create non-overlapping-in-time test folds with an explicit embargo."""
    if not start_ts < end_ts or train_seconds <= 0 or test_seconds <= 0:
        raise ValueError("invalid walk-forward range or window")
    if embargo_seconds < 0:
        raise ValueError("embargo_seconds must be non-negative")
    step = step_seconds or test_seconds
    if step <= 0:
        raise ValueError("step_seconds must be positive")
    folds: list[WalkForwardFold] = []
    test_start = start_ts + train_seconds + embargo_seconds
    index = 0
    while test_start < end_ts:
        test_end = min(test_start + test_seconds, end_ts)
        train_end = test_start - embargo_seconds
        folds.append(WalkForwardFold(index, test_start - embargo_seconds - train_seconds,
                                     train_end, test_start, test_end, embargo_seconds))
        index += 1
        test_start += step
    return tuple(folds)


def run_walkforward(
    folds: Sequence[WalkForwardFold],
    evaluator_factory: Callable[[WalkForwardFold], Callable[[WalkForwardFold], object]],
) -> WalkForwardResult:
    """Evaluate folds with a newly-created evaluator for every fold.

    The factory is intentionally called inside the loop: callers construct a
    fresh broker, cash ledger, strategy state, and risk guards there.  The
    harness never reuses an evaluator or carries results into the next fold.
    """
    reports: list[object] = []
    for fold in folds:
        evaluator = evaluator_factory(fold)
        reports.append(evaluator(fold))
    return WalkForwardResult(tuple(folds), tuple(reports))


__all__ = ["WalkForwardFold", "WalkForwardResult", "rolling_folds", "run_walkforward"]
