"""Versioned sports external-provider adapter boundary (§10.3).

No concrete provider is selected here — that is an operator decision recorded
in §10.2. This module is the *contract* every approved provider adapter must
satisfy before its data can reach a sports paper decision:

- an explicit allowlist (provider name + domain) and an entitlement/terms
  record, both required for a row to be `usable`;
- raw provenance: source URL, raw content hash, observed / available /
  retrieved timestamps, and a parser version;
- a provider event/market -> Kalshi ticker mapping that must be declared, not
  guessed;
- a parse/version status per row (`parsed` | `parse_error` | `unmapped` |
  `disallowed_source` | `stale`);
- conflict detection across two eligible providers for the same claim, with a
  pre-registered resolution rule; and
- a machine-readable coverage/gap report (missing expected snapshots are
  reported, never back-filled).

It builds on `sports/external.py` (the raw boundary) and `sports/evidence.py`
(allowlist + causal timing + conflict grouping) rather than replacing them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from kalshi_bot.data.sports.evidence import SourceAllowlist
from kalshi_bot.data.sports.external import ExternalSportsObservation

ParseStatus = str  # "parsed" | "parse_error" | "unmapped" | "disallowed_source" | "stale"


@dataclass(frozen=True)
class ProviderEntitlement:
    """Operator-recorded terms for one provider (from §10.2 review)."""

    provider: str
    terms_url: str
    retention_days: int
    attribution_required: bool
    max_requests_per_minute: int
    historical_snapshots: bool

    def valid(self) -> bool:
        return bool(self.provider and self.terms_url and self.retention_days >= 0)


@dataclass(frozen=True)
class MarketMapping:
    """Declared provider-event -> Kalshi-market identity."""

    provider_event_id: str
    provider_market_id: str
    kalshi_market_ticker: str
    kalshi_series_ticker: str


@dataclass(frozen=True)
class ProviderRow:
    """One normalized provider observation with full provenance + status."""

    provider: str
    endpoint_url: str
    claim: str
    value: object
    observed_at: int
    available_at: int
    retrieved_at: int
    raw_content: str
    parser_version: str
    kalshi_market_ticker: str | None
    status: ParseStatus
    reason: str | None = None
    provenance: dict[str, object] = field(default_factory=dict)

    @property
    def raw_content_hash(self) -> str:
        return hashlib.sha256(self.raw_content.encode("utf-8")).hexdigest()

    def causal_at(self, decision_ts: int) -> bool:
        return self.observed_at <= decision_ts and self.available_at <= decision_ts


def normalize_observation(
    obs: ExternalSportsObservation,
    *,
    claim: str,
    parser_version: str,
    allowlist: SourceAllowlist,
    entitlement: ProviderEntitlement | None,
    mapping: MarketMapping | None,
    raw_content: str,
    now_ts: int,
) -> ProviderRow:
    """Turn a raw boundary observation into a status-tagged provider row.

    Fail-closed: a disallowed source, missing entitlement, missing mapping, or
    a future availability all produce a non-`parsed` status rather than an
    exception, so a batch import records every rejection.
    """
    base = dict(
        provider=obs.provider,
        endpoint_url=obs.endpoint,
        claim=claim,
        value=obs.value,
        observed_at=obs.observed_at,
        available_at=obs.available_at,
        retrieved_at=now_ts,
        raw_content=raw_content,
        parser_version=parser_version,
        provenance=dict(obs.provenance),
    )
    if not allowlist.permits(obs.provider, obs.endpoint):
        return ProviderRow(**base, kalshi_market_ticker=None, status="disallowed_source",
                           reason="source_not_allowlisted")
    if entitlement is None or not entitlement.valid() or entitlement.provider != obs.provider:
        return ProviderRow(**base, kalshi_market_ticker=None, status="parse_error",
                           reason="missing_entitlement_record")
    if mapping is None:
        return ProviderRow(**base, kalshi_market_ticker=None, status="unmapped",
                           reason="no_declared_market_mapping")
    if obs.available_at > now_ts:
        return ProviderRow(**base, kalshi_market_ticker=mapping.kalshi_market_ticker,
                           status="stale", reason="not_yet_available")
    return ProviderRow(
        **base, kalshi_market_ticker=mapping.kalshi_market_ticker, status="parsed"
    )


@dataclass(frozen=True)
class ConflictResult:
    claim: str
    market_ticker: str | None
    conflicted: bool
    resolved_provider: str | None
    reason: str


def detect_conflicts(
    rows: Iterable[ProviderRow],
    *,
    decision_ts: int,
    resolution_priority: Sequence[str] = (),
) -> list[ConflictResult]:
    """Group causal `parsed` rows by (market, claim); flag incompatible values.

    Two rows conflict when their `value` differs. The pre-registered
    `resolution_priority` (an ordered provider list) picks a winner; without a
    matching priority the claim stays `conflicted` and a dependent entry is
    blocked by the caller.
    """
    groups: dict[tuple[str | None, str], list[ProviderRow]] = {}
    for row in rows:
        if row.status != "parsed" or not row.causal_at(decision_ts):
            continue
        groups.setdefault((row.kalshi_market_ticker, row.claim), []).append(row)

    results: list[ConflictResult] = []
    for (ticker, claim), group in groups.items():
        values = {_hashable(r.value) for r in group}
        if len(values) <= 1:
            results.append(ConflictResult(claim, ticker, False, group[0].provider, "agree"))
            continue
        winner = next(
            (p for p in resolution_priority if any(r.provider == p for r in group)),
            None,
        )
        if winner is not None:
            results.append(
                ConflictResult(claim, ticker, False, winner, "resolved_by_priority")
            )
        else:
            results.append(
                ConflictResult(claim, ticker, True, None, "conflicted_no_resolution_rule")
            )
    return results


def _hashable(value: object) -> object:
    if isinstance(value, dict):
        return tuple(sorted((k, _hashable(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_hashable(v) for v in value)
    return value


@dataclass(frozen=True)
class GapReport:
    market_ticker: str
    claim: str
    expected_interval_s: int
    window_start_ts: int
    window_end_ts: int
    observed_count: int
    missing_intervals: tuple[tuple[int, int], ...]

    @property
    def has_gaps(self) -> bool:
        return bool(self.missing_intervals)

    def as_dict(self) -> dict[str, object]:
        return {
            "market_ticker": self.market_ticker,
            "claim": self.claim,
            "expected_interval_s": self.expected_interval_s,
            "window": [self.window_start_ts, self.window_end_ts],
            "observed_count": self.observed_count,
            "missing_intervals": [list(m) for m in self.missing_intervals],
            "has_gaps": self.has_gaps,
        }


def build_gap_report(
    rows: Sequence[ProviderRow],
    *,
    market_ticker: str,
    claim: str,
    window_start_ts: int,
    window_end_ts: int,
    expected_interval_s: int,
) -> GapReport:
    """Report expected snapshot intervals with no causal observation.

    Missing intervals are *reported*, never filled — the same discipline the
    market-data lake uses. An interval counts as covered if any row's
    `observed_at` falls within it.
    """
    if expected_interval_s <= 0 or window_end_ts <= window_start_ts:
        raise ValueError("invalid gap-report window")
    stamps = sorted(
        r.observed_at
        for r in rows
        if r.kalshi_market_ticker == market_ticker
        and r.claim == claim
        and r.status == "parsed"
        and window_start_ts <= r.observed_at <= window_end_ts
    )
    missing: list[tuple[int, int]] = []
    cursor = window_start_ts
    idx = 0
    while cursor < window_end_ts:
        bucket_end = min(cursor + expected_interval_s, window_end_ts)
        covered = False
        while idx < len(stamps) and stamps[idx] < bucket_end:
            if stamps[idx] >= cursor:
                covered = True
            idx += 1
        if not covered:
            missing.append((cursor, bucket_end))
        cursor = bucket_end
    return GapReport(
        market_ticker=market_ticker,
        claim=claim,
        expected_interval_s=expected_interval_s,
        window_start_ts=window_start_ts,
        window_end_ts=window_end_ts,
        observed_count=len(stamps),
        missing_intervals=tuple(missing),
    )


__all__ = [
    "ConflictResult",
    "GapReport",
    "MarketMapping",
    "ParseStatus",
    "ProviderEntitlement",
    "ProviderRow",
    "build_gap_report",
    "detect_conflicts",
    "normalize_observation",
]
