"""Versioned, explicit admission thresholds for external source quality."""

from __future__ import annotations

from dataclasses import dataclass

from kalshi_bot.data.quality import CoverageReport


@dataclass(frozen=True)
class QualityPolicy:
    version: str = "2026-09-brti-reconstruction-v2"
    min_rows: int = 100
    max_gap_seconds: int = 900
    max_source_lag_seconds: int = 120
    max_cross_source_price_diff: float = 0.01
    min_resolution_agreement: float | None = None
    """Admission threshold on `resolution_agreement` (brti-constituent-
    history §D4). Deliberately left unset pending the first measurement
    (design.md Open Questions) -- an unset threshold means this check is
    skipped, not defaulted permissive or restrictive by guesswork."""


@dataclass(frozen=True)
class QualityVerdict:
    asset: str
    eligible: bool
    reason: str
    policy_version: str


DEFAULT_QUALITY_POLICY = QualityPolicy()


def evaluate_quality(
    asset: str,
    report: CoverageReport,
    *,
    policy: QualityPolicy = DEFAULT_QUALITY_POLICY,
    compatible_source: bool = True,
) -> QualityVerdict:
    if report.rows < policy.min_rows:
        reason = "no_data" if report.rows == 0 else "insufficient_coverage"
    elif any(end - start > policy.max_gap_seconds for start, end in report.gaps):
        reason = "coverage_gap"
    elif (report.max_source_lag_ms or 0) > policy.max_source_lag_seconds * 1000:
        reason = "stale_data"
    elif not compatible_source:
        reason = "incompatible_index"
    else:
        return QualityVerdict(asset, True, "pass", policy.version)
    return QualityVerdict(asset, False, reason, policy.version)


def evaluate_reconstruction_quality(
    asset: str,
    *,
    status: str,
    resolution_agreement: float | None,
    policy: QualityPolicy = DEFAULT_QUALITY_POLICY,
) -> QualityVerdict:
    """Admission check for a reconstruction-error report.

    An `unmeasured` reconstruction never passes (§D4 / the
    synthetic-index-reconstruction spec's "unmeasured is unvalidated"
    requirement). When `policy.min_resolution_agreement` is unset, a
    measured reconstruction is reported `pass` without a numeric bar --
    the threshold has deliberately not been chosen yet.
    """
    if status != "measured" or resolution_agreement is None:
        return QualityVerdict(asset, False, "unmeasured", policy.version)
    if (
        policy.min_resolution_agreement is not None
        and resolution_agreement < policy.min_resolution_agreement
    ):
        return QualityVerdict(asset, False, "resolution_agreement_below_threshold", policy.version)
    return QualityVerdict(asset, True, "pass", policy.version)


__all__ = [
    "DEFAULT_QUALITY_POLICY",
    "QualityPolicy",
    "QualityVerdict",
    "evaluate_quality",
    "evaluate_reconstruction_quality",
]
