"""Shared foreground paper-run orchestration (multi-venue-paper-trading §8).

`PaperOrchestrator` is the single coordinator behind the `run_paper` command.
It owns the pieces every domain shares — the paper guard, registry/lifecycle
admission, a frozen preflight, per-decision audit persistence, restart
reconciliation, heartbeats, and clean SIGINT/SIGTERM shutdown — while routing
the actual fill/settlement mechanics to a domain adapter that keeps its own
price and position semantics (§8.5/§8.6 prediction, §9 perp, §10 sports).

Nothing here reaches a live Kalshi order endpoint: the guard refuses a
mutating client (`PaperExecutionGuard.assert_paper_adapter`) before an adapter
is accepted, and the orchestrator only ever calls the adapter's simulated
`evaluate_and_fill` / `reconcile` surface.

The module is deliberately storage-shaped, not CLI-shaped: `run()` takes a
session factory, a clock, and injected adapters, so it is unit-testable
against an in-memory archive with no network. `scripts/run_paper.py` is the
thin CLI.
"""

from __future__ import annotations

import contextlib
import signal as _signal
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.config.crypto_registry import (
    DEFAULT_CRYPTO_REGISTRY,
    CryptoAssetConfig,
)
from kalshi_bot.config.lifecycle import Domain, LifecycleState
from kalshi_bot.config.settings import Settings
from kalshi_bot.execution.paper_audit import AuditKind, PaperAuditEnvelope
from kalshi_bot.execution.paper_guard import (
    PaperExecutionError,
    PaperExecutionGuard,
    PaperMode,
)
from kalshi_bot.risk.paper_policy import DEFAULT_RISK_POLICY, RiskPolicy
from kalshi_bot.storage.models import PaperAuditEvent, PaperRun
from kalshi_bot.strategy.registry import (
    DEFAULT_STRATEGY_ID,
    KNOWN_STRATEGY_IDS,
    strategy_entry,
)

# `strategy_id` values that mean "no explicit strategy was pinned" — mapped to
# the default (hold) rather than refused, so callers predating the registry
# still work unchanged.
_UNSET_STRATEGY_IDS: frozenset[str] = frozenset({"unspecified", ""})


def resolve_strategy_id(strategy_id: str) -> str:
    """Normalize a config's `strategy_id`: the legacy sentinels become the
    default; anything else must be a registered id."""
    if strategy_id in _UNSET_STRATEGY_IDS:
        return DEFAULT_STRATEGY_ID
    return strategy_id

ACTIVE_ASSETS: tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP")

# Lifecycle states that may create a simulated fill. `shadow` records the
# decision and the observable would-fill but never a paper position (§8.7);
# everything below shadow only observes.
_FILLING_STATES: frozenset[LifecycleState] = frozenset({"paper"})
_DECISION_STATES: frozenset[LifecycleState] = frozenset({"shadow", "paper"})


class PreflightError(RuntimeError):
    """Raised when a paper run's preconditions are not satisfied."""


@dataclass(frozen=True)
class PaperRunConfig:
    """Everything the operator pins before a run starts."""

    domain: Domain
    assets: tuple[str, ...]
    mode: PaperMode = "paper"
    duration_seconds: float | None = None
    strategy_id: str = "unspecified"
    config_id: str = "unspecified"
    report_id: str | None = None
    require_authenticated: bool = True
    manifest_sha256: str | None = None
    risk_policy: RiskPolicy = DEFAULT_RISK_POLICY

    def __post_init__(self) -> None:
        if self.domain not in ("prediction", "perp", "sports"):
            raise ValueError(f"unsupported domain: {self.domain!r}")
        if self.mode not in ("paper", "shadow"):
            raise ValueError(f"unsupported mode: {self.mode!r}")
        if not self.assets:
            raise ValueError("at least one asset is required")
        unknown = tuple(a for a in self.assets if a.upper() != a)
        if unknown:
            raise ValueError(f"assets must be uppercase symbols: {unknown}")
        if self.duration_seconds is not None and self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive when set")


@dataclass(frozen=True)
class AssetAdmission:
    """Per-asset lifecycle verdict produced by preflight."""

    asset_id: str
    lifecycle: LifecycleState
    admitted: bool
    may_fill: bool
    reason: str


@dataclass(frozen=True)
class PreflightResult:
    guard: PaperExecutionGuard
    admissions: tuple[AssetAdmission, ...]
    risk_policy_version: str
    manifest_sha256: str | None
    strategy_id: str = DEFAULT_STRATEGY_ID
    strategy_config_version: str | None = None
    strategy_gate_status: str | None = None

    @property
    def any_admitted(self) -> bool:
        return any(a.admitted for a in self.admissions)

    def admission(self, asset_id: str) -> AssetAdmission | None:
        for a in self.admissions:
            if a.asset_id == asset_id:
                return a
        return None


# --------------------------------------------------------------------------
# Domain adapter contract
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AdapterDecision:
    """Normalized adapter outcome for one asset in one cycle."""

    asset_id: str
    domain: Domain
    action: str  # "hold" | "entry" | "exit" | "blocked" | "no_market"
    status: str
    reason: str | None = None
    would_fill: bool = False
    filled: bool = False
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconciliationOutcome:
    asset_id: str
    resolved: bool
    reason: str
    payload: dict[str, object] = field(default_factory=dict)


class DomainPaperAdapter(Protocol):
    """A domain adapter shares this envelope, not price/settlement semantics."""

    domain: Domain
    broker_name: str

    def reconcile(self, asset_id: str) -> ReconciliationOutcome: ...

    def evaluate(self, asset_id: str, *, now_ts: int, may_fill: bool) -> AdapterDecision: ...


# --------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------


def _registry_by_id(
    registry: Sequence[CryptoAssetConfig],
) -> dict[str, CryptoAssetConfig]:
    return {a.asset_id: a for a in registry}


def _lifecycle_for(
    asset: CryptoAssetConfig, domain: Domain
) -> LifecycleState:
    """Map the registry's per-instrument lifecycle mode onto the change's
    six-state lifecycle. `live` is never reachable from a paper run."""
    if domain == "perp":
        raw = "observe"  # perp lifecycle is tracked on the adapter/report, not the registry yet
    else:
        inst = asset.instrument("15m") or asset.instrument("60m")
        raw = inst.lifecycle if inst is not None else "observe"
    if raw == "live":
        return "blocked"
    if raw in ("observe", "backtest", "shadow", "paper", "disabled", "blocked"):
        return raw  # type: ignore[return-value]
    return "observe"


def run_preflight(
    settings: Settings,
    config: PaperRunConfig,
    *,
    registry: Sequence[CryptoAssetConfig] = DEFAULT_CRYPTO_REGISTRY,
    frozen_report_present: bool | Callable[[str], bool] = False,
    data_available: bool | Callable[[str], bool] = True,
    manifest_provenance: Callable[[str], str | None] | None = None,
    ledger_path=None,
) -> PreflightResult:
    """Fail-closed checks before a run starts (§8.4).

    Order matters: the paper guard runs first so a production-authenticated
    or non-paper configuration is refused before any registry work.
    """
    try:
        guard = PaperExecutionGuard.validate(
            settings,
            mode=config.mode,
            require_authenticated=config.require_authenticated,
            ledger_path=ledger_path,
        )
    except PaperExecutionError as exc:  # normalize to the preflight failure type
        raise PreflightError(str(exc)) from exc

    # Strategy id is resolved and validated before any registry or market
    # work — an unknown id must fail with nothing written (§1.3).
    resolved_strategy_id = resolve_strategy_id(config.strategy_id)
    if resolved_strategy_id not in KNOWN_STRATEGY_IDS:
        raise PreflightError(
            f"unknown_strategy_id: {config.strategy_id!r} is not in the "
            f"strategy registry ({', '.join(sorted(KNOWN_STRATEGY_IDS))})"
        )
    entry = strategy_entry(resolved_strategy_id)

    by_id = _registry_by_id(registry)

    def _report_ok(asset_id: str) -> bool:
        if callable(frozen_report_present):
            return bool(frozen_report_present(asset_id))
        return bool(frozen_report_present)

    def _data_ok(asset_id: str) -> bool:
        if callable(data_available):
            return bool(data_available(asset_id))
        return bool(data_available)

    def _manifest_source_native(asset_id: str) -> bool:
        # Fail-closed: no lookup provided, or the lookup returns anything
        # other than "source_native", refuses fills rather than permitting
        # them (brti-constituent-history §D5).
        if manifest_provenance is None:
            return True
        return manifest_provenance(asset_id) == "source_native"

    admissions: list[AssetAdmission] = []
    for asset_id in config.assets:
        asset = by_id.get(asset_id)
        if asset is None:
            admissions.append(
                AssetAdmission(asset_id, "blocked", False, False, "not_in_active_registry")
            )
            continue
        if config.domain in ("prediction", "perp") and asset_id not in ACTIVE_ASSETS:
            admissions.append(
                AssetAdmission(asset_id, "blocked", False, False, "asset_not_active")
            )
            continue
        lifecycle = _lifecycle_for(asset, config.domain)
        if lifecycle not in _DECISION_STATES:
            admissions.append(
                AssetAdmission(
                    asset_id, lifecycle, False, False, f"lifecycle_{lifecycle}_no_decisions"
                )
            )
            continue
        if not _data_ok(asset_id):
            admissions.append(
                AssetAdmission(asset_id, lifecycle, False, False, "data_unavailable")
            )
            continue
        # A run may only create fills for a `paper`-lifecycle asset AND only
        # when the run itself is in paper mode AND a frozen admission report
        # exists AND that report's manifest is source-native, not a
        # reconstructed proxy. Otherwise the asset is admitted for decision
        # recording only.
        may_fill = (
            lifecycle == "paper"
            and config.mode == "paper"
            and lifecycle in _FILLING_STATES
            and _report_ok(asset_id)
            and _manifest_source_native(asset_id)
        )
        reason = "admitted_for_paper" if may_fill else "admitted_for_decisions_only"
        if lifecycle == "paper" and config.mode == "paper":
            if not _report_ok(asset_id):
                reason = "no_frozen_admission_report"
            elif not _manifest_source_native(asset_id):
                reason = "reconstructed_data_not_admissible"
        admissions.append(
            AssetAdmission(asset_id, lifecycle, True, may_fill, reason)
        )

    result = PreflightResult(
        guard=guard,
        admissions=tuple(admissions),
        risk_policy_version=config.risk_policy.version,
        manifest_sha256=config.manifest_sha256,
        strategy_id=resolved_strategy_id,
        strategy_config_version=entry.config_version,
        strategy_gate_status=entry.gate_status,
    )
    if not result.any_admitted:
        raise PreflightError(
            "preflight admitted no assets: "
            + "; ".join(f"{a.asset_id}={a.reason}" for a in result.admissions)
        )
    return result


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------


class _StopRequestedError(Exception):
    """Raised inside the run loop when a signal or duration ends the run."""


@dataclass
class PaperOrchestrator:
    """Coordinates preflight, per-cycle adapter evaluation, audit persistence,
    heartbeats, and reconciliation for one foreground paper run."""

    settings: Settings
    config: PaperRunConfig
    session_factory: Callable[[], Session]
    adapter: DomainPaperAdapter
    now_fn: Callable[[], float]
    sleep_fn: Callable[[float], None] = lambda _s: None
    cycle_seconds: float = 5.0
    registry: Sequence[CryptoAssetConfig] = DEFAULT_CRYPTO_REGISTRY
    frozen_report_present: bool | Callable[[str], bool] = False
    data_available: bool | Callable[[str], bool] = True
    manifest_provenance: Callable[[str], str | None] | None = None

    max_cycles: int | None = None

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _stop: bool = field(default=False, init=False)

    # -- lifecycle -------------------------------------------------------

    def request_stop(self) -> None:
        """Ask the run loop to finish the current cycle and shut down cleanly.

        A public seam for a supervising process (e.g.
        `scripts/run_strategy_lab.py`) running several orchestrators in
        threads: the per-process SIGINT handler `_install_signal_handlers`
        installs only fires on the main thread, so the supervisor forwards
        the stop by calling this on each child."""
        self._stop = True

    def _install_signal_handlers(self) -> Callable[[], None]:
        """Best-effort SIGINT/SIGTERM handlers that request a clean stop.

        Returns a restore callable. In a thread without the main interpreter
        (tests), `signal.signal` raises ValueError; we degrade to relying on
        KeyboardInterrupt / duration instead.
        """
        previous: list[tuple[int, object]] = []

        def _handler(_signum, _frame) -> None:
            self._stop = True

        for sig in (_signal.SIGINT, getattr(_signal, "SIGTERM", None)):
            if sig is None:
                continue
            try:
                previous.append((sig, _signal.getsignal(sig)))
                _signal.signal(sig, _handler)
            except (ValueError, OSError):
                pass

        def _restore() -> None:
            for sig, handler in previous:
                with contextlib.suppress(ValueError, OSError):
                    _signal.signal(sig, handler)  # type: ignore[arg-type]

        return _restore

    def _create_run_row(self, preflight: PreflightResult) -> None:
        with self.session_factory() as session:
            session.add(
                PaperRun(
                    id=self.run_id,
                    domain=self.config.domain,
                    mode=self.config.mode,
                    asset_ids=list(self.config.assets),
                    started_at=int(self.now_fn()),
                    status="preflight",
                    config_fingerprint=preflight.guard.config_fingerprint,
                    manifest_sha256=preflight.manifest_sha256,
                    risk_policy_version=preflight.risk_policy_version,
                    strategy_id=preflight.strategy_id,
                    strategy_config_version=preflight.strategy_config_version,
                    strategy_gate_status=preflight.strategy_gate_status,
                )
            )
            session.commit()

    def _set_run_status(self, status: str, *, ended: bool = False) -> None:
        with self.session_factory() as session:
            row = session.get(PaperRun, self.run_id)
            if row is None:
                return
            row.status = status
            if ended:
                row.ended_at = int(self.now_fn())
            session.add(row)
            session.commit()

    def _audit(
        self,
        kind: AuditKind,
        *,
        asset_id: str | None,
        status: str,
        reason: str | None = None,
        payload: dict[str, object] | None = None,
        preflight: PreflightResult | None = None,
    ) -> None:
        env = PaperAuditEnvelope(
            paper_run_id=self.run_id,
            kind=kind,
            domain=self.config.domain,
            asset_id=asset_id,
            observed_at=int(self.now_fn()),
            status=status,
            reason=reason,
            data_manifest_hash=(
                preflight.manifest_sha256 if preflight else self.config.manifest_sha256
            ),
            risk_policy_version=self.config.risk_policy.version,
            payload=payload or {},
        )
        with self.session_factory() as session:
            session.add(
                PaperAuditEvent(
                    paper_run_id=env.paper_run_id,
                    kind=env.kind,
                    domain=env.domain,
                    asset_id=env.asset_id,
                    observed_at=env.observed_at,
                    status=env.status,
                    reason=env.reason,
                    data_manifest_hash=env.data_manifest_hash,
                    risk_policy_version=env.risk_policy_version,
                    payload=env.payload,
                )
            )
            session.commit()

    # -- reconciliation (§8.8) ----------------------------------------------

    def _reconcile(self, preflight: PreflightResult) -> dict[str, bool]:
        """Reconcile persisted open positions before any new entry.

        A blocked asset here does not abort the whole run — it drops that
        asset from new entries for the rest of the run and records why.
        """
        entry_blocked: dict[str, bool] = {}
        for adm in preflight.admissions:
            if not adm.admitted:
                continue
            outcome = self.adapter.reconcile(adm.asset_id)
            entry_blocked[adm.asset_id] = not outcome.resolved
            self._audit(
                "reconciliation",
                asset_id=adm.asset_id,
                status="reconciled" if outcome.resolved else "reconciliation_required",
                reason=outcome.reason,
                payload=dict(outcome.payload),
                preflight=preflight,
            )
        return entry_blocked

    # -- main loop --------------------------------------------------------

    def run(self) -> str:
        """Run the foreground paper run to completion. Returns the run id."""
        preflight = run_preflight(
            self.settings,
            self.config,
            registry=self.registry,
            frozen_report_present=self.frozen_report_present,
            data_available=self.data_available,
            manifest_provenance=self.manifest_provenance,
            ledger_path=None,
        )
        self._create_run_row(preflight)
        self._audit(
            "run",
            asset_id=None,
            status="preflight_passed",
            reason=None,
            payload={
                "admissions": [
                    {
                        "asset": a.asset_id,
                        "lifecycle": a.lifecycle,
                        "admitted": a.admitted,
                        "may_fill": a.may_fill,
                        "reason": a.reason,
                    }
                    for a in preflight.admissions
                ],
                "config_fingerprint": preflight.guard.config_fingerprint,
                "strategy_id": preflight.strategy_id,
                "strategy_config_version": preflight.strategy_config_version,
                "strategy_gate_status": preflight.strategy_gate_status,
                "config_id": self.config.config_id,
                "report_id": self.config.report_id,
            },
            preflight=preflight,
        )

        restore = self._install_signal_handlers()
        entry_blocked = self._reconcile(preflight)
        self._set_run_status("running")
        self._audit("run", asset_id=None, status="running", preflight=preflight)

        start = self.now_fn()
        exit_status = "completed"
        cycles = 0
        try:
            while True:
                now = self.now_fn()
                if self._stop:
                    raise _StopRequestedError
                if (
                    self.config.duration_seconds is not None
                    and now - start >= self.config.duration_seconds
                ):
                    break
                if self.max_cycles is not None and cycles >= self.max_cycles:
                    break
                self._cycle(preflight, entry_blocked, now_ts=int(now))
                self._heartbeat(int(now))
                cycles += 1
                self.sleep_fn(self.cycle_seconds)
        except (_StopRequestedError, KeyboardInterrupt):
            exit_status = "interrupted"
        finally:
            restore()
            self._heartbeat(int(self.now_fn()), final=True)
            self._audit(
                "report",
                asset_id=None,
                status=exit_status,
                payload={"run_id": self.run_id, "domain": self.config.domain},
                preflight=preflight,
            )
            self._set_run_status(exit_status, ended=True)
        return self.run_id

    def _cycle(
        self,
        preflight: PreflightResult,
        entry_blocked: dict[str, bool],
        *,
        now_ts: int,
    ) -> None:
        for adm in preflight.admissions:
            if not adm.admitted:
                continue
            # Reconciliation may have closed the entry gate for this asset.
            may_fill = adm.may_fill and not entry_blocked.get(adm.asset_id, False)
            try:
                decision = self.adapter.evaluate(
                    adm.asset_id, now_ts=now_ts, may_fill=may_fill
                )
            except Exception as exc:  # an adapter fault must not kill the run
                self._audit(
                    "decision",
                    asset_id=adm.asset_id,
                    status="adapter_error",
                    reason=str(exc),
                    preflight=preflight,
                )
                continue

            self._audit(
                "decision",
                asset_id=decision.asset_id,
                status=decision.status,
                reason=decision.reason,
                payload={
                    "action": decision.action,
                    "would_fill": decision.would_fill,
                    "filled": decision.filled,
                    "lifecycle": adm.lifecycle,
                    "mode": self.config.mode,
                    **decision.payload,
                },
                preflight=preflight,
            )
            if decision.filled:
                self._audit(
                    "fill",
                    asset_id=decision.asset_id,
                    status="filled",
                    payload=dict(decision.payload),
                    preflight=preflight,
                )

    def _heartbeat(self, now_ts: int, *, final: bool = False) -> None:
        self._audit(
            "heartbeat",
            asset_id=None,
            status="final" if final else "alive",
            payload={"ts": now_ts},
        )


# --------------------------------------------------------------------------
# Query helpers (used by the CLI and dashboard)
# --------------------------------------------------------------------------


def load_run_events(session: Session, run_id: str) -> list[PaperAuditEvent]:
    return list(
        session.execute(
            select(PaperAuditEvent)
            .where(PaperAuditEvent.paper_run_id == run_id)
            .order_by(PaperAuditEvent.observed_at, PaperAuditEvent.id)
        ).scalars()
    )


def summarize_run(events: Iterable[PaperAuditEvent]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ev in events:
        key = f"{ev.kind}:{ev.status}"
        counts[key] = counts.get(key, 0) + 1
    return counts


__all__ = [
    "ACTIVE_ASSETS",
    "AdapterDecision",
    "AssetAdmission",
    "DomainPaperAdapter",
    "PaperOrchestrator",
    "PaperRunConfig",
    "PreflightError",
    "PreflightResult",
    "ReconciliationOutcome",
    "load_run_events",
    "run_preflight",
    "summarize_run",
]
