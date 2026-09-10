"""Run-health and reconciliation reporting for paper runs (multi-venue §12.4).

Reads the domain-neutral `paper_audit_events` written by
:class:`~kalshi_bot.execution.orchestrator.PaperOrchestrator` and turns them
into an operator-facing report that keeps the six outcomes distinct:

``no_signal``          the adapter evaluated and chose to hold — nothing wrong.
``policy_block``       a risk/lifecycle/admission rule refused the entry.
``stale_data``         a required quote / mark / evidence value was too old.
``missing_coverage``   no market, no listed contract, no fillable quote.
``execution_rejected`` a would-fill was attempted and the paper broker said no.
``system_failure``     an adapter raised, or reconciliation is unresolved.

Ledgers are reported per domain and never merged. When a frozen backtest
summary is supplied, a divergence block compares realized fill / rejection /
hold rates against it so a promoted scope that starts behaving differently is
visible immediately (the §11.6 ``paper_backtest_divergence`` trigger).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.storage import PaperAuditEvent, PaperRun

# -- outcome taxonomy ------------------------------------------------------

NO_SIGNAL = "no_signal"
POLICY_BLOCK = "policy_block"
STALE_DATA = "stale_data"
MISSING_COVERAGE = "missing_coverage"
EXECUTION_REJECTED = "execution_rejected"
SYSTEM_FAILURE = "system_failure"
FILLED = "filled"

OUTCOMES = (
    FILLED,
    NO_SIGNAL,
    POLICY_BLOCK,
    STALE_DATA,
    MISSING_COVERAGE,
    EXECUTION_REJECTED,
    SYSTEM_FAILURE,
)

# Decision `status` strings emitted by the domain adapters, mapped to an
# outcome bucket. Anything unrecognised falls through to `policy_block`
# (a named refusal we simply haven't catalogued) rather than being counted
# as a healthy hold.
_STATUS_OUTCOME: dict[str, str] = {
    # healthy holds
    "hold": NO_SIGNAL,
    "shadow_no_fill": NO_SIGNAL,
    "position_already_open": NO_SIGNAL,
    # fills
    "filled": FILLED,
    "shadow_would_fill": FILLED,  # a shadow fill is a would-fill, still "would have traded"
    # stale inputs
    "stale_quote": STALE_DATA,
    "stale_evidence": STALE_DATA,
    "stale_mark": STALE_DATA,
    "mark_unavailable_reconcile": STALE_DATA,
    # coverage gaps
    "no_market": MISSING_COVERAGE,
    "no_listed_market": MISSING_COVERAGE,
    "no_fillable_quote": MISSING_COVERAGE,
    "non_binary_shape": MISSING_COVERAGE,
    # execution rejections
    "order_rejected": EXECUTION_REJECTED,
    "invalid_signal": EXECUTION_REJECTED,
    # policy / admission blocks
    "admission_blocked": POLICY_BLOCK,
    "classification_rejected": POLICY_BLOCK,
    "in_play_rejected": POLICY_BLOCK,
    "evidence_blocked": POLICY_BLOCK,
    "evidence_conflicted": POLICY_BLOCK,
    "copy_trading_unsupported": POLICY_BLOCK,
    "risk_blocked": POLICY_BLOCK,
    "unsupported_domain": POLICY_BLOCK,
    # faults
    "adapter_error": SYSTEM_FAILURE,
}


def classify_status(status: str) -> str:
    """Map one decision `status` to an outcome bucket."""
    if status in _STATUS_OUTCOME:
        return _STATUS_OUTCOME[status]
    if status.startswith("shadow_"):
        return NO_SIGNAL
    if status.startswith(("stale", "no_", "missing")):
        return MISSING_COVERAGE if status.startswith(("no_", "missing")) else STALE_DATA
    return POLICY_BLOCK


# -- reports -------------------------------------------------------------


@dataclass(frozen=True)
class ReconciliationStatus:
    """Per-asset reconciliation state at the last observation."""

    asset_id: str
    resolved: bool
    reason: str | None
    observed_at: int


@dataclass(frozen=True)
class DomainLedger:
    """One domain's outcome counts within a run — never merged with another."""

    domain: str
    outcome_counts: dict[str, int] = field(default_factory=dict)
    by_asset: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def decisions(self) -> int:
        return sum(self.outcome_counts.values())

    @property
    def fills(self) -> int:
        return self.outcome_counts.get(FILLED, 0)

    @property
    def healthy(self) -> bool:
        return (
            self.outcome_counts.get(SYSTEM_FAILURE, 0) == 0
            and self.outcome_counts.get(STALE_DATA, 0) == 0
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "domain": self.domain,
            "decisions": self.decisions,
            "outcome_counts": dict(self.outcome_counts),
            "by_asset": {a: dict(c) for a, c in self.by_asset.items()},
            "healthy": self.healthy,
        }


@dataclass(frozen=True)
class DivergenceMetric:
    metric: str
    paper_rate: float
    backtest_rate: float
    abs_delta: float
    exceeds: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "paper_rate": round(self.paper_rate, 4),
            "backtest_rate": round(self.backtest_rate, 4),
            "abs_delta": round(self.abs_delta, 4),
            "exceeds": self.exceeds,
        }


@dataclass(frozen=True)
class RunHealthReport:
    run_id: str
    domain: str
    status: str
    started_at: int
    ended_at: int | None
    ledgers: dict[str, DomainLedger]
    reconciliation: list[ReconciliationStatus]
    heartbeats: int
    last_heartbeat_ts: int | None
    divergence: list[DivergenceMetric] = field(default_factory=list)

    @property
    def unresolved_reconciliation(self) -> list[ReconciliationStatus]:
        return [r for r in self.reconciliation if not r.resolved]

    @property
    def system_failures(self) -> int:
        return sum(led.outcome_counts.get(SYSTEM_FAILURE, 0) for led in self.ledgers.values())

    @property
    def healthy(self) -> bool:
        return (
            not self.unresolved_reconciliation
            and self.system_failures == 0
            and all(led.healthy for led in self.ledgers.values())
        )

    @property
    def blocks_new_entries(self) -> bool:
        """Any unresolved reconciliation blocks new entries for the whole run
        (the §8.8 / §9.7 / §10.6 rule)."""
        return bool(self.unresolved_reconciliation) or self.system_failures > 0

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "domain": self.domain,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "heartbeats": self.heartbeats,
            "last_heartbeat_ts": self.last_heartbeat_ts,
            "ledgers": {d: led.as_dict() for d, led in self.ledgers.items()},
            "reconciliation": [
                {
                    "asset_id": r.asset_id,
                    "resolved": r.resolved,
                    "reason": r.reason,
                    "observed_at": r.observed_at,
                }
                for r in self.reconciliation
            ],
            "unresolved_reconciliation": [r.asset_id for r in self.unresolved_reconciliation],
            "divergence": [d.as_dict() for d in self.divergence],
            "healthy": self.healthy,
            "blocks_new_entries": self.blocks_new_entries,
        }


def build_run_health_report(
    session: Session,
    run_id: str,
    *,
    backtest_summary: Mapping[str, float] | None = None,
    divergence_threshold: float = 0.15,
) -> RunHealthReport:
    """Assemble the run-health + reconciliation report for one paper run."""
    run = session.get(PaperRun, run_id)
    if run is None:
        raise KeyError(f"unknown paper run: {run_id!r}")
    events = list(
        session.execute(
            select(PaperAuditEvent)
            .where(PaperAuditEvent.paper_run_id == run_id)
            .order_by(PaperAuditEvent.observed_at, PaperAuditEvent.id)
        ).scalars()
    )
    ledgers = _build_ledgers(events)
    reconciliation = _latest_reconciliation(events)
    heartbeats = [e for e in events if e.kind == "heartbeat"]
    divergence = (
        _divergence(ledgers.get(run.domain), backtest_summary, divergence_threshold)
        if backtest_summary is not None
        else []
    )
    return RunHealthReport(
        run_id=run_id,
        domain=run.domain,
        status=run.status,
        started_at=run.started_at,
        ended_at=run.ended_at,
        ledgers=ledgers,
        reconciliation=reconciliation,
        heartbeats=len(heartbeats),
        last_heartbeat_ts=heartbeats[-1].observed_at if heartbeats else None,
        divergence=divergence,
    )


def _build_ledgers(events: Iterable[PaperAuditEvent]) -> dict[str, DomainLedger]:
    counts: dict[str, dict[str, int]] = {}
    by_asset: dict[str, dict[str, dict[str, int]]] = {}
    for ev in events:
        if ev.kind != "decision":
            continue
        outcome = classify_status(ev.status)
        dom = ev.domain
        counts.setdefault(dom, {})
        counts[dom][outcome] = counts[dom].get(outcome, 0) + 1
        if ev.asset_id:
            by_asset.setdefault(dom, {}).setdefault(ev.asset_id, {})
            asset_counts = by_asset[dom][ev.asset_id]
            asset_counts[outcome] = asset_counts.get(outcome, 0) + 1
    return {
        dom: DomainLedger(domain=dom, outcome_counts=c, by_asset=by_asset.get(dom, {}))
        for dom, c in counts.items()
    }


def _latest_reconciliation(events: Iterable[PaperAuditEvent]) -> list[ReconciliationStatus]:
    latest: dict[str, ReconciliationStatus] = {}
    for ev in events:
        if ev.kind != "reconciliation":
            continue
        asset = ev.asset_id or "(run)"
        latest[asset] = ReconciliationStatus(
            asset_id=asset,
            resolved=ev.status == "reconciled",
            reason=ev.reason,
            observed_at=ev.observed_at,
        )
    return sorted(latest.values(), key=lambda r: r.asset_id)


def _divergence(
    ledger: DomainLedger | None,
    backtest_summary: Mapping[str, float],
    threshold: float,
) -> list[DivergenceMetric]:
    if ledger is None or ledger.decisions == 0:
        return []
    total = ledger.decisions
    paper_rates = {
        "fill_rate": ledger.outcome_counts.get(FILLED, 0) / total,
        "rejection_rate": ledger.outcome_counts.get(EXECUTION_REJECTED, 0) / total,
        "hold_rate": ledger.outcome_counts.get(NO_SIGNAL, 0) / total,
    }
    metrics: list[DivergenceMetric] = []
    for name, paper_rate in paper_rates.items():
        if name not in backtest_summary:
            continue
        bt = float(backtest_summary[name])
        delta = abs(paper_rate - bt)
        metrics.append(
            DivergenceMetric(
                metric=name,
                paper_rate=paper_rate,
                backtest_rate=bt,
                abs_delta=delta,
                exceeds=delta > threshold,
            )
        )
    return metrics


__all__ = [
    "EXECUTION_REJECTED",
    "FILLED",
    "MISSING_COVERAGE",
    "NO_SIGNAL",
    "OUTCOMES",
    "POLICY_BLOCK",
    "STALE_DATA",
    "SYSTEM_FAILURE",
    "DivergenceMetric",
    "DomainLedger",
    "ReconciliationStatus",
    "RunHealthReport",
    "build_run_health_report",
    "classify_status",
]
