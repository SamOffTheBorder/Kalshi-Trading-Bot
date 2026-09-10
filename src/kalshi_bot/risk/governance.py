"""Cross-domain emergency control and lifecycle governance (multi-venue §11.4-11.6).

Two durable, append-only ledgers sit above every paper domain:

- :class:`GlobalEmergencyControl` — one halt state for the whole process.
  Drawdown, daily-loss, consecutive-loss, simulated liquidation / margin
  breach, data-integrity faults, process signals (SIGINT/SIGTERM), pending
  reconciliation, and an explicit operator request all route through the same
  :func:`GlobalEmergencyControl.halt`. A halt blocks new entries in *every*
  paper domain immediately (§11.4) and persists an
  :class:`~kalshi_bot.storage.models.EmergencyHaltRecord`. ``resume`` needs an
  explicit operator id plus a fresh health/reconciliation check that returns
  clean; a bare process restart re-reads the latest row and stays halted
  (§11.5).

- :class:`LifecycleGovernor` — per asset/domain/candidate promotion and
  demotion records. A promotion must carry frozen data/model/risk fingerprints
  and passing gate results. Poor coverage, paper/backtest divergence, liquidity
  deterioration, a data-integrity failure, or a halted risk state demote the
  affected scope to ``blocked`` (or an earlier state) without touching any
  other scope (§11.6). No transition may target ``live``.

Neither ledger enforces order routing itself — the paper adapters and the
orchestrator call :func:`GlobalEmergencyControl.blocks_entry` before every
entry and consult :func:`LifecycleGovernor.current_state` for the scope.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.config.lifecycle import LifecycleState, validate_lifecycle
from kalshi_bot.storage.models import EmergencyHaltRecord, LifecycleTransitionRecord

# --- emergency control ------------------------------------------------------

HALT_SOURCES = frozenset(
    {
        "operator",
        "drawdown",
        "daily_loss",
        "consecutive_loss",
        "liquidation",
        "margin_breach",
        "data_integrity",
        "process_signal",
        "reconciliation",
    }
)


@dataclass(frozen=True)
class HaltStatus:
    """Current global halt state derived from the latest ledger row."""

    halted: bool
    halt_id: str | None
    source: str | None
    reason: str | None
    since_ts: int | None

    def blocks_entry(self) -> bool:
        return self.halted


@dataclass(frozen=True)
class HealthCheck:
    """Result of the fresh health/reconciliation check a resume requires."""

    healthy: bool
    unresolved: tuple[str, ...] = ()

    @classmethod
    def clean(cls) -> HealthCheck:
        return cls(healthy=True, unresolved=())


HealthCheckFn = Callable[[], HealthCheck]


class ResumeRefusedError(RuntimeError):
    """Raised when a resume is attempted without an operator or a clean check."""


@dataclass
class GlobalEmergencyControl:
    """Durable single-writer view over ``emergency_halt_records``.

    Construct one per process; it reads the latest persisted row on every call
    so a second process observes the same state. It never caches a "not
    halted" conclusion across calls.
    """

    session: Session
    now_fn: Callable[[], int]
    policy_version: str | None = None

    # -- reads -------------------------------------------------------------

    def _latest(self) -> EmergencyHaltRecord | None:
        return self.session.execute(
            select(EmergencyHaltRecord).order_by(EmergencyHaltRecord.id.desc()).limit(1)
        ).scalar_one_or_none()

    def status(self) -> HaltStatus:
        row = self._latest()
        if row is None or row.action == "resume":
            return HaltStatus(False, None, None, None, None)
        return HaltStatus(
            halted=True,
            halt_id=row.halt_id,
            source=row.source,
            reason=row.reason,
            since_ts=row.created_at,
        )

    def blocks_entry(self) -> bool:
        return self.status().halted

    # -- writes ----------------------------------------------------------

    def halt(
        self,
        *,
        source: str,
        reason: str,
        paper_run_id: str | None = None,
        domain: str | None = None,
        asset_id: str | None = None,
        operator: str | None = None,
        policy_snapshot: dict | None = None,
    ) -> HaltStatus:
        """Record a halt. Idempotent while already halted: the existing
        ``halt_id`` is kept and the new trigger is logged, so a second cause
        firing during a halt does not reset the clock or lose the first
        reason."""
        if source not in HALT_SOURCES:
            raise ValueError(f"unknown halt source: {source!r}")
        current = self.status()
        if current.halted:
            logger.warning(
                "emergency halt already active ({}: {}); additional trigger {}: {}",
                current.source,
                current.reason,
                source,
                reason,
            )
            self.session.add(
                EmergencyHaltRecord(
                    halt_id=current.halt_id,
                    action="halt",
                    source=source,
                    reason=f"additional_trigger: {reason}",
                    created_at=self.now_fn(),
                    paper_run_id=paper_run_id,
                    domain=domain,
                    asset_id=asset_id,
                    operator=operator,
                    policy_version=self.policy_version,
                    policy_snapshot=policy_snapshot,
                )
            )
            self.session.flush()
            return current
        halt_id = uuid.uuid4().hex
        logger.warning("EMERGENCY HALT {} ({}): {}", halt_id, source, reason)
        self.session.add(
            EmergencyHaltRecord(
                halt_id=halt_id,
                action="halt",
                source=source,
                reason=reason,
                created_at=self.now_fn(),
                paper_run_id=paper_run_id,
                domain=domain,
                asset_id=asset_id,
                operator=operator,
                policy_version=self.policy_version,
                policy_snapshot=policy_snapshot,
            )
        )
        self.session.flush()
        return self.status()

    def resume(
        self,
        *,
        operator: str,
        health_check: HealthCheckFn,
        note: str = "operator resume",
    ) -> HaltStatus:
        """Clear the active halt. Requires a non-empty operator id and a
        ``health_check`` that returns ``healthy=True``. A restart alone can
        never reach here — there is no auto-resume path."""
        if not operator or not operator.strip():
            raise ResumeRefusedError("resume requires an explicit operator id")
        current = self.status()
        if not current.halted:
            return current
        result = health_check()
        if not result.healthy:
            unresolved = ", ".join(result.unresolved) or "unspecified"
            logger.warning(
                "resume refused for halt {}: unresolved [{}]", current.halt_id, unresolved
            )
            raise ResumeRefusedError(f"unresolved conditions block resume: {unresolved}")
        logger.warning(
            "EMERGENCY RESUME {} approved by {}: {}", current.halt_id, operator, note
        )
        self.session.add(
            EmergencyHaltRecord(
                halt_id=current.halt_id,
                action="resume",
                source="operator",
                reason=note,
                created_at=self.now_fn(),
                operator=operator,
                policy_version=self.policy_version,
                health_snapshot={"healthy": True, "unresolved": []},
            )
        )
        self.session.flush()
        return self.status()

    def history(self) -> list[EmergencyHaltRecord]:
        return list(
            self.session.execute(
                select(EmergencyHaltRecord).order_by(EmergencyHaltRecord.id.asc())
            ).scalars()
        )


# --- lifecycle promotion / demotion ---------------------------------------

_ORDER: dict[LifecycleState, int] = {
    "disabled": 0,
    "observe": 1,
    "backtest": 2,
    "shadow": 3,
    "paper": 4,
    "blocked": -1,  # terminal-until-review, not on the promotion ladder
}

DEMOTION_TRIGGERS = frozenset(
    {
        "poor_coverage",
        "paper_backtest_divergence",
        "liquidity_deterioration",
        "data_integrity_failure",
        "source_alignment_failure",
        "emergency_halt",
        "operator_request",
    }
)

PROMOTION_GATES = (
    "data_coverage",
    "out_of_sample_validation",
    "execution_assumptions",
    "shadow_period",
    "paper_admission_report",
    "risk_policy",
)


@dataclass(frozen=True)
class PromotionEvidence:
    """Frozen fingerprints and gate results that justify a promotion."""

    report_id: str
    data_manifest_hash: str
    model_fingerprint: str
    risk_policy_version: str
    gate_results: dict[str, bool] = field(default_factory=dict)

    def failing_gates(self, required: Sequence[str] = PROMOTION_GATES) -> list[str]:
        return [g for g in required if not self.gate_results.get(g, False)]


class PromotionRefusedError(RuntimeError):
    """Raised when a promotion lacks fingerprints or a required gate fails."""


@dataclass
class LifecycleGovernor:
    """Append-only promotion/demotion ledger keyed by ``ASSET:domain:candidate``.

    ``current_state`` is the ``to_state`` of the newest row for a scope, or the
    supplied ``default_state`` when the scope has no history.
    """

    session: Session
    now_fn: Callable[[], int]
    default_state: LifecycleState = "observe"

    @staticmethod
    def scope_key(asset_id: str, domain: str, candidate: str) -> str:
        return f"{asset_id}:{domain}:{candidate}"

    def _latest(self, scope_key: str) -> LifecycleTransitionRecord | None:
        return self.session.execute(
            select(LifecycleTransitionRecord)
            .where(LifecycleTransitionRecord.scope_key == scope_key)
            .order_by(LifecycleTransitionRecord.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def current_state(self, asset_id: str, domain: str, candidate: str) -> LifecycleState:
        row = self._latest(self.scope_key(asset_id, domain, candidate))
        if row is None:
            return self.default_state
        return validate_lifecycle(row.to_state)

    def promote(
        self,
        *,
        asset_id: str,
        domain: str,
        candidate: str,
        to_state: LifecycleState,
        operator: str,
        evidence: PromotionEvidence,
        required_gates: Sequence[str] = PROMOTION_GATES,
    ) -> LifecycleState:
        target = validate_lifecycle(to_state)
        if target in {"blocked", "disabled"}:
            raise PromotionRefusedError("use demote() to reach blocked/disabled")
        if not operator or not operator.strip():
            raise PromotionRefusedError("promotion requires an explicit operator id")
        current = self.current_state(asset_id, domain, candidate)
        if current == "blocked":
            raise PromotionRefusedError("scope is blocked; clear the block before promotion")
        if _ORDER[target] <= _ORDER[current]:
            raise PromotionRefusedError(
                f"promotion must advance the ladder ({current} -> {target} is not forward)"
            )
        if _ORDER[target] - _ORDER[current] > 1:
            raise PromotionRefusedError(
                f"promotion skips a stage ({current} -> {target}); advance one step at a time"
            )
        missing = [
            name
            for name, val in (
                ("report_id", evidence.report_id),
                ("data_manifest_hash", evidence.data_manifest_hash),
                ("model_fingerprint", evidence.model_fingerprint),
                ("risk_policy_version", evidence.risk_policy_version),
            )
            if not val
        ]
        if missing:
            raise PromotionRefusedError(f"promotion missing frozen fingerprints: {missing}")
        failing = evidence.failing_gates(required_gates)
        if failing:
            raise PromotionRefusedError(f"promotion gates failing: {failing}")
        self.session.add(
            LifecycleTransitionRecord(
                scope_key=self.scope_key(asset_id, domain, candidate),
                asset_id=asset_id,
                domain=domain,
                candidate=candidate,
                direction="promote",
                from_state=current,
                to_state=target,
                trigger="operator_promotion",
                reason=f"gates passed: {sorted(required_gates)}",
                created_at=self.now_fn(),
                operator=operator,
                report_id=evidence.report_id,
                data_manifest_hash=evidence.data_manifest_hash,
                model_fingerprint=evidence.model_fingerprint,
                risk_policy_version=evidence.risk_policy_version,
                gate_results=dict(evidence.gate_results),
            )
        )
        self.session.flush()
        logger.info(
            "lifecycle promote {}:{}:{} {} -> {} by {}",
            asset_id,
            domain,
            candidate,
            current,
            target,
            operator,
        )
        return target

    def demote(
        self,
        *,
        asset_id: str,
        domain: str,
        candidate: str,
        trigger: str,
        reason: str,
        to_state: LifecycleState = "blocked",
        operator: str | None = None,
    ) -> LifecycleState:
        if trigger not in DEMOTION_TRIGGERS:
            raise ValueError(f"unknown demotion trigger: {trigger!r}")
        target = validate_lifecycle(to_state)
        current = self.current_state(asset_id, domain, candidate)
        if target != "blocked" and _ORDER[target] >= _ORDER[current] >= 0:
            raise ValueError(
                f"demotion must move backward or to blocked ({current} -> {target})"
            )
        self.session.add(
            LifecycleTransitionRecord(
                scope_key=self.scope_key(asset_id, domain, candidate),
                asset_id=asset_id,
                domain=domain,
                candidate=candidate,
                direction="demote",
                from_state=current,
                to_state=target,
                trigger=trigger,
                reason=reason,
                created_at=self.now_fn(),
                operator=operator,
            )
        )
        self.session.flush()
        logger.warning(
            "lifecycle demote {}:{}:{} {} -> {} ({}: {})",
            asset_id,
            domain,
            candidate,
            current,
            target,
            trigger,
            reason,
        )
        return target

    def history(
        self, asset_id: str, domain: str, candidate: str
    ) -> list[LifecycleTransitionRecord]:
        return list(
            self.session.execute(
                select(LifecycleTransitionRecord)
                .where(
                    LifecycleTransitionRecord.scope_key
                    == self.scope_key(asset_id, domain, candidate)
                )
                .order_by(LifecycleTransitionRecord.id.asc())
            ).scalars()
        )


__all__ = [
    "DEMOTION_TRIGGERS",
    "HALT_SOURCES",
    "PROMOTION_GATES",
    "GlobalEmergencyControl",
    "HaltStatus",
    "HealthCheck",
    "LifecycleGovernor",
    "PromotionEvidence",
    "PromotionRefusedError",
    "ResumeRefusedError",
]
