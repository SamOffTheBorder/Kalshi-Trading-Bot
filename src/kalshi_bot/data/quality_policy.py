"""Versioned, explicit admission thresholds for external source quality."""

from __future__ import annotations

from dataclasses import dataclass

from kalshi_bot.data.quality import CoverageReport


@dataclass(frozen=True)
class QualityPolicy:
    version: str = "2026-09-paper-v1"
    min_rows: int = 100
    max_gap_seconds: int = 900
    max_source_lag_seconds: int = 120
    max_cross_source_price_diff: float = 0.01


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


__all__ = ["DEFAULT_QUALITY_POLICY", "QualityPolicy", "QualityVerdict", "evaluate_quality"]
