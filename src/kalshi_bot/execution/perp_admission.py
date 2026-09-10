"""Fresh perpetual paper-admission verdict for BTC/ETH/SOL/XRP (§9.6).

A perpetual asset is admitted to a paper fill only when ALL of these hold:

- it is one of the four active assets (an unconfigured perp the margin API
  returns — e.g. AAVE — is recorded elsewhere as non-active and never lands
  here);
- a fresh, eligible `PerpDiscovery` snapshot exists (multiplier, minimum
  order size, reference index, active status, non-stale metadata);
- a fresh mark observation is available within the freshness bound;
- realized funding coverage is available (an estimate alone is not enough —
  it may inform risk but is never booked, so it cannot gate admission);
- a frozen strategy-validation / paper-admission report is present for that
  exact asset; and
- the run is a paper-mode run.

Every failing check yields an explicit reason string so the dashboard and
the run log can say precisely why an entry is blocked.
"""

from __future__ import annotations

from dataclasses import dataclass

from kalshi_bot.discovery.service import DiscoverySnapshot

ACTIVE_PERP_ASSETS: frozenset[str] = frozenset({"BTC", "ETH", "SOL", "XRP"})


@dataclass(frozen=True)
class PerpMarkCoverage:
    latest_mark_observed_at: int | None
    latest_funding_observed_at: int | None
    has_realized_funding: bool


@dataclass(frozen=True)
class PerpAdmissionVerdict:
    asset_id: str
    admitted: bool
    reason: str
    may_fill: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "admitted": self.admitted,
            "reason": self.reason,
            "may_fill": self.may_fill,
        }


def evaluate_perp_admission(
    *,
    asset_id: str,
    now_ts: int,
    discovery: DiscoverySnapshot | None,
    coverage: PerpMarkCoverage,
    frozen_report_present: bool,
    paper_mode: bool,
    max_metadata_age_s: int = 900,
    max_mark_age_s: int = 120,
    max_funding_age_s: int = 8 * 3600 + 900,
) -> PerpAdmissionVerdict:
    asset = asset_id.upper()
    if asset not in ACTIVE_PERP_ASSETS:
        return PerpAdmissionVerdict(asset, False, "asset_not_active", False)

    if discovery is None:
        return PerpAdmissionVerdict(asset, False, "no_discovery_snapshot", False)
    if discovery.asset_id != asset or discovery.instrument != "perp":
        return PerpAdmissionVerdict(asset, False, "discovery_snapshot_mismatch", False)
    if not discovery.eligible:
        return PerpAdmissionVerdict(
            asset, False, discovery.failure_reason or "discovery_ineligible", False
        )
    if now_ts - discovery.checked_at > max_metadata_age_s:
        return PerpAdmissionVerdict(asset, False, "stale_discovery_snapshot", False)

    meta = discovery.metadata
    if meta.get("multiplier") is None or meta.get("minimum_order_size") is None:
        return PerpAdmissionVerdict(asset, False, "perp_missing_contract_parameters", False)
    if meta.get("reference_index") is None:
        return PerpAdmissionVerdict(asset, False, "perp_missing_reference_index", False)

    if (
        coverage.latest_mark_observed_at is None
        or now_ts - coverage.latest_mark_observed_at > max_mark_age_s
    ):
        return PerpAdmissionVerdict(asset, False, "no_fresh_mark", False)

    if not coverage.has_realized_funding or coverage.latest_funding_observed_at is None:
        return PerpAdmissionVerdict(asset, False, "no_realized_funding_coverage", False)
    if now_ts - coverage.latest_funding_observed_at > max_funding_age_s:
        return PerpAdmissionVerdict(asset, False, "stale_realized_funding", False)

    if not frozen_report_present:
        return PerpAdmissionVerdict(asset, True, "admitted_for_decisions_only", False)
    if not paper_mode:
        return PerpAdmissionVerdict(asset, True, "shadow_mode_no_paper_fill", False)

    return PerpAdmissionVerdict(asset, True, "admitted_for_paper", True)


__all__ = [
    "ACTIVE_PERP_ASSETS",
    "PerpAdmissionVerdict",
    "PerpMarkCoverage",
    "evaluate_perp_admission",
]
