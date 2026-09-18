"""Deterministic, bounded council orchestration over typed agent artifacts."""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from typing import Any, cast

from kalshi_bot.agents.contracts import (
    AgentDefinitionSnapshot,
    AgentRole,
    AgentUsage,
    AgentVerdictArtifact,
    CouncilDecisionArtifact,
    CouncilPolicyResult,
    CouncilRunState,
    EvidenceBundle,
    TradeCandidateEnvelope,
)
from kalshi_bot.agents.evidence import project_for_role
from kalshi_bot.agents.gateway import (
    AgentCallResult,
    AgentClient,
    AgentRequest,
    format_repair_request,
)
from kalshi_bot.agents.profiles import (
    DEFAULT_COUNCIL_PROFILES,
    CouncilProfile,
    RoleConfig,
    resolve_profile,
)
from kalshi_bot.agents.prompts import build_role_prompt
from kalshi_bot.agents.validation import validate_master_decision, validate_verdict_artifact

_ROLE_ORDER: tuple[AgentRole, ...] = (
    "researcher",
    "bull_thesis",
    "bear_thesis",
    "skeptic",
    "execution_liquidity",
    "rules_settlement",
    "portfolio_risk",
    "master_synthesizer",
)


class CouncilRoutingError(RuntimeError):
    """The candidate cannot be routed to an enabled compatible council."""


@dataclass(frozen=True)
class CouncilCheckpoint:
    stage: str
    council_run_id: str
    artifact_ids: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RoleAttempt:
    role: AgentRole
    attempt: int
    status: str
    request_hash: str
    verdict: AgentVerdictArtifact | None = None
    raw_output: str | None = None
    errors: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class CouncilRunResult:
    council_run_id: str
    candidate: TradeCandidateEnvelope
    evidence: EvidenceBundle
    profile: CouncilProfile
    state: CouncilRunState
    snapshots: tuple[AgentDefinitionSnapshot, ...]
    attempts: tuple[RoleAttempt, ...]
    policy: CouncilPolicyResult
    decision: CouncilDecisionArtifact
    checkpoints: tuple[CouncilCheckpoint, ...]
    reason_codes: tuple[str, ...] = ()
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class _BudgetLedger:
    output_tokens: int = 0
    cost_usd: float = 0.0

    def can_reserve(self, role: RoleConfig, profile: CouncilProfile) -> bool:
        return (
            self.output_tokens + role.max_output_tokens <= profile.budget.total_output_tokens
            and self.cost_usd + role.max_cost_usd <= profile.budget.total_cost_usd
        )

    def record(self, verdict: AgentVerdictArtifact | None, raw_output: str | None) -> None:
        if verdict is not None:
            self.output_tokens += verdict.usage.output_tokens
            self.cost_usd += verdict.usage.cost_usd
        elif raw_output:
            self.output_tokens += max(1, len(raw_output) // 4)


class CouncilCoordinator:
    """Run independent specialists, deterministic policy, and one master call.

    The coordinator accepts only an ``AgentClient`` mapping. It has no broker,
    credential, or database parameter, so a model cannot acquire an execution
    surface through council orchestration.
    """

    def __init__(
        self,
        clients: Mapping[AgentRole, AgentClient],
        *,
        profiles: tuple[CouncilProfile, ...] = DEFAULT_COUNCIL_PROFILES,
        now_fn: Callable[[], float] = time.monotonic,
        checkpoint_fn: Callable[[CouncilCheckpoint], None] | None = None,
    ) -> None:
        self._clients = clients
        self._profiles = profiles
        self._now_fn = now_fn
        self._checkpoint_fn = checkpoint_fn

    def run(
        self,
        candidate: TradeCandidateEnvelope,
        evidence: EvidenceBundle,
        *,
        council_run_id: str | None = None,
        enable_reconsideration: bool = False,
        completed_attempts: tuple[RoleAttempt, ...] = (),
    ) -> CouncilRunResult:
        if candidate.candidate_id != evidence.candidate_id:
            raise ValueError("candidate and evidence bundle IDs do not match")
        if candidate.domain != evidence.domain:
            raise ValueError("candidate and evidence bundle domains do not match")
        profile = resolve_profile(candidate.specialization_key, profiles=self._profiles)
        if profile is None or profile.domain != candidate.domain or profile.lifecycle == "disabled":
            raise CouncilRoutingError(
                f"no compatible council profile for {candidate.specialization_key}"
            )
        enabled_specialists = [
            role
            for role in profile.roles
            if role.role != "master_synthesizer"
            and role.model.enabled
            and role.role in self._clients
        ]
        if not enabled_specialists:
            raise CouncilRoutingError(
                f"no enabled specialist client for {candidate.specialization_key}"
            )

        run_id = council_run_id or uuid.uuid4().hex
        prior = {
            attempt.role: attempt
            for attempt in completed_attempts
            if attempt.verdict is not None
        }
        if any(
            attempt.verdict is None
            or attempt.verdict.council_run_id != run_id
            or attempt.verdict.evidence_bundle_hash != evidence.bundle_hash
            for attempt in completed_attempts
        ):
            raise ValueError("completed attempts do not belong to this council run")
        checkpoints: list[CouncilCheckpoint] = []
        attempts: list[RoleAttempt] = list(prior.values())
        snapshots = tuple(self._snapshot(profile, role) for role in profile.roles)
        self._checkpoint(
            checkpoints,
            CouncilCheckpoint(
                "evidence",
                run_id,
                (evidence.bundle_hash,),
                {"candidate_id": candidate.candidate_id},
            ),
        )

        ledger = _BudgetLedger()
        first_roles = [
            role
            for role in profile.roles
            if role.role != "master_synthesizer" and role.model.enabled
            and role.role not in prior
        ]
        reserved, skipped = self._reserve_roles(first_roles, profile, ledger)
        for role in skipped:
            attempts.append(
                self._fallback_attempt(role, run_id, candidate, evidence, "budget_exhausted")
            )
        first_attempts = self._execute_first_round(
            reserved,
            profile=profile,
            run_id=run_id,
            candidate=candidate,
            evidence=evidence,
            ledger=ledger,
        )
        attempts.extend(first_attempts)
        self._checkpoint(
            checkpoints,
            CouncilCheckpoint(
                "roles",
                run_id,
                tuple(attempt.verdict.verdict_id for attempt in attempts if attempt.verdict),
                {"attempts": len(attempts)},
            ),
        )

        policy = calculate_policy(profile, [attempt.verdict for attempt in attempts])
        self._checkpoint(
            checkpoints,
            CouncilCheckpoint(
                "policy",
                run_id,
                (),
                {"reason_codes": list(policy.reason_codes)},
            ),
        )

        if enable_reconsideration and profile.budget.max_reconsideration_rounds:
            revisions = self._reconsider(
                attempts,
                policy,
                profile=profile,
                run_id=run_id,
                candidate=candidate,
                evidence=evidence,
                ledger=ledger,
            )
            attempts.extend(revisions)
            if revisions:
                policy = calculate_policy(profile, [attempt.verdict for attempt in attempts])
                latest = {
                    attempt.role: attempt.verdict
                    for attempt in revisions
                    if attempt.verdict is not None
                }
                bull = latest.get("bull_thesis")
                bear = latest.get("bear_thesis")
                if (
                    bull is not None
                    and bear is not None
                    and bull.decision != "abstain"
                    and bear.decision != "abstain"
                    and bull.decision != bear.decision
                ):
                    policy = policy.model_copy(
                        update={
                            "reason_codes": (
                                *policy.reason_codes,
                                "unresolved_disagreement",
                            )
                        }
                    )
                self._checkpoint(
                    checkpoints,
                    CouncilCheckpoint(
                        "reconsideration",
                        run_id,
                        tuple(
                            attempt.verdict.verdict_id
                            for attempt in revisions
                            if attempt.verdict
                        ),
                        {"round": 1},
                    ),
                )

        if not policy.can_synthesize:
            decision = hold_decision(
                run_id, policy, "deterministic policy did not permit synthesis"
            )
            reason_codes = tuple(dict.fromkeys((*policy.reason_codes, "hold_before_master")))
        else:
            master_config = next(
                role for role in profile.roles if role.role == "master_synthesizer"
            )
            master_attempt = self._execute_master(
                master_config,
                profile=profile,
                run_id=run_id,
                candidate=candidate,
                evidence=evidence,
                attempts=attempts,
                policy=policy,
                ledger=ledger,
            )
            attempts.append(master_attempt)
            decision = self._decision_from_master(
                master_attempt,
                candidate=candidate,
                policy=policy,
                run_id=run_id,
                verdict_ids=(attempt.verdict.verdict_id for attempt in attempts if attempt.verdict),
            )
            reason_codes = tuple(
                dict.fromkeys(
                    (*policy.reason_codes, *master_attempt.errors)
                    if master_attempt.errors
                    else policy.reason_codes
                )
            )
            self._checkpoint(
                checkpoints,
                CouncilCheckpoint(
                    "master",
                    run_id,
                    (decision.decision_id,),
                    {"outcome": decision.outcome},
                ),
            )

        self._checkpoint(
            checkpoints,
            CouncilCheckpoint(
                "completed",
                run_id,
                (decision.decision_id,),
                {"outcome": decision.outcome},
            ),
        )
        return CouncilRunResult(
            council_run_id=run_id,
            candidate=candidate,
            evidence=evidence,
            profile=profile,
            state="completed",
            snapshots=snapshots,
            attempts=tuple(sorted(attempts, key=lambda item: (item.role, item.attempt))),
            policy=policy,
            decision=decision,
            checkpoints=tuple(checkpoints),
            reason_codes=reason_codes,
            output_tokens=ledger.output_tokens,
            cost_usd=ledger.cost_usd,
        )

    def _snapshot(self, profile: CouncilProfile, role: RoleConfig) -> AgentDefinitionSnapshot:
        permissions = tuple(
            permission
            for permission, enabled in (
                ("price_ceiling", role.allow_price_ceiling),
                ("size_ceiling", role.allow_size_ceiling),
            )
            if enabled
        )
        return AgentDefinitionSnapshot(
            agent_id=f"{profile.profile_id}:{role.role}",
            role=role.role,
            provider=role.model.provider,
            model=role.model.model,
            prompt_version="council-role-v1",
            schema_version="council-contract-v1",
            permissions=permissions,
        )

    def _checkpoint(
        self, checkpoints: list[CouncilCheckpoint], checkpoint: CouncilCheckpoint
    ) -> None:
        checkpoints.append(checkpoint)
        if self._checkpoint_fn is not None:
            self._checkpoint_fn(checkpoint)

    @staticmethod
    def _reserve_roles(
        roles: list[RoleConfig], profile: CouncilProfile, ledger: _BudgetLedger
    ) -> tuple[list[RoleConfig], list[RoleConfig]]:
        reserved: list[RoleConfig] = []
        skipped: list[RoleConfig] = []
        for role in roles:
            if ledger.can_reserve(role, profile):
                reserved.append(role)
                ledger.output_tokens += role.max_output_tokens
                ledger.cost_usd += role.max_cost_usd
            else:
                skipped.append(role)
        # Reservations only decide what may start. Actual usage is computed
        # after calls; reset so the result reports observed usage, not maxima.
        ledger.output_tokens = 0
        ledger.cost_usd = 0.0
        return reserved, skipped

    def _request(
        self,
        role: RoleConfig,
        *,
        run_id: str,
        candidate: TradeCandidateEnvelope,
        evidence: EvidenceBundle,
        attempt: int = 1,
        payload_override: dict[str, Any] | None = None,
    ) -> AgentRequest:
        payload = payload_override or project_for_role(candidate, evidence, role.role)
        if payload_override is None:
            payload = {**payload, "prompt": build_role_prompt(role.role, payload)}
        return AgentRequest(
            role=role.role,
            agent_id=f"{run_id}:{role.role}",
            payload=payload,
            timeout_seconds=role.timeout_seconds,
            max_output_tokens=role.max_output_tokens,
            max_cost_usd=role.max_cost_usd,
            attempt=attempt,
        )

    def _invoke(self, request: AgentRequest) -> AgentCallResult:
        client = self._clients.get(request.role)
        if client is None:
            return AgentCallResult(
                "failed", None, request.request_hash, 0, "no_enabled_agent_client"
            )
        return client.invoke(request)

    def _execute_first_round(
        self,
        roles: list[RoleConfig],
        *,
        profile: CouncilProfile,
        run_id: str,
        candidate: TradeCandidateEnvelope,
        evidence: EvidenceBundle,
        ledger: _BudgetLedger,
    ) -> list[RoleAttempt]:
        requests = [
            self._request(role, run_id=run_id, candidate=candidate, evidence=evidence)
            for role in roles
        ]
        calls = self._invoke_concurrently(requests, profile.budget.max_concurrency)
        results: list[RoleAttempt] = []
        for role, request, call in sorted(
            zip(roles, requests, calls, strict=True), key=lambda item: item[0].role
        ):
            attempt = self._parse_or_repair(
                role,
                request,
                call,
                run_id=run_id,
                candidate=candidate,
                evidence=evidence,
                profile=profile,
            )
            ledger.record(attempt.verdict, attempt.raw_output)
            results.append(attempt)
        return results

    def _invoke_concurrently(
        self, requests: list[AgentRequest], max_concurrency: int
    ) -> list[AgentCallResult]:
        if not requests:
            return []
        executor = ThreadPoolExecutor(max_workers=min(max_concurrency, len(requests)))
        futures = [executor.submit(self._invoke, request) for request in requests]
        started = self._now_fn()
        results: list[AgentCallResult] = []
        try:
            for future, request in zip(futures, requests, strict=True):
                remaining = max(0.0, request.timeout_seconds - (self._now_fn() - started))
                try:
                    results.append(future.result(timeout=remaining))
                except TimeoutError:
                    future.cancel()
                    results.append(
                        AgentCallResult(
                            "timeout",
                            None,
                            request.request_hash,
                            int((self._now_fn() - started) * 1000),
                            "council_deadline_exceeded",
                        )
                    )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return results

    def _parse_or_repair(
        self,
        role: RoleConfig,
        request: AgentRequest,
        call: AgentCallResult,
        *,
        run_id: str,
        candidate: TradeCandidateEnvelope,
        evidence: EvidenceBundle,
        profile: CouncilProfile,
    ) -> RoleAttempt:
        parsed, errors = self._parse_verdict(role, request, call, evidence)
        if parsed is not None:
            return RoleAttempt(
                role.role,
                request.attempt,
                call.status,
                request.request_hash,
                parsed,
                call.raw_output,
            )
        if (
            call.status == "completed"
            and profile.budget.max_format_retries
            and request.attempt == 1
            and call.raw_output is not None
        ):
            repair = format_repair_request(request, call.raw_output, list(errors))
            repair_call = self._invoke(repair)
            repaired, repair_errors = self._parse_verdict(role, repair, repair_call, evidence)
            if repaired is not None:
                repaired = repaired.model_copy(update={"parse_status": "repaired"})
                return RoleAttempt(
                    role.role,
                    repair.attempt,
                    repair_call.status,
                    repair.request_hash,
                    repaired,
                    repair_call.raw_output,
                    tuple(repair_errors),
                    repair_call.error,
                )
            errors = tuple(dict.fromkeys((*errors, *repair_errors)))
            call = repair_call
            request = repair
        fallback = self._fallback_verdict(
            role,
            run_id=run_id,
            candidate=candidate,
            evidence=evidence,
            attempt=request.attempt,
            errors=errors or (call.error or call.status,),
            latency_ms=call.latency_ms,
            raw_output=call.raw_output,
        )
        return RoleAttempt(
            role.role,
            request.attempt,
            call.status,
            request.request_hash,
            fallback,
            call.raw_output,
            tuple(errors),
            call.error,
        )

    @staticmethod
    def _parse_verdict(
        role: RoleConfig,
        request: AgentRequest,
        call: AgentCallResult,
        evidence: EvidenceBundle,
    ) -> tuple[AgentVerdictArtifact | None, tuple[str, ...]]:
        if call.status != "completed" or call.raw_output is None:
            return None, (call.error or call.status,)
        try:
            artifact = AgentVerdictArtifact.model_validate_json(call.raw_output)
        except Exception as exc:
            return None, (f"schema:{type(exc).__name__}",)
        artifact = artifact.model_copy(
            update={
                "attempt": request.attempt,
                "raw_output_hash": hashlib.sha256(call.raw_output.encode()).hexdigest(),
                "usage": artifact.usage.model_copy(
                    update={"latency_ms": call.latency_ms}
                ),
            }
        )
        errors = validate_verdict_artifact(artifact, bundle=evidence, role_config=role)
        if artifact.council_run_id != request.agent_id.split(":", 1)[0]:
            errors = (*errors, "council_run_mismatch")
        return (artifact if not errors else None), errors

    def _fallback_attempt(
        self,
        role: RoleConfig,
        run_id: str,
        candidate: TradeCandidateEnvelope,
        evidence: EvidenceBundle,
        reason: str,
    ) -> RoleAttempt:
        verdict = self._fallback_verdict(
            role,
            run_id=run_id,
            candidate=candidate,
            evidence=evidence,
            attempt=1,
            errors=(reason,),
            latency_ms=None,
            raw_output=None,
        )
        return RoleAttempt(role.role, 1, "not_started", "", verdict, errors=(reason,))

    @staticmethod
    def _fallback_verdict(
        role: RoleConfig,
        *,
        run_id: str,
        candidate: TradeCandidateEnvelope,
        evidence: EvidenceBundle,
        attempt: int,
        errors: tuple[str, ...],
        latency_ms: int | None,
        raw_output: str | None,
    ) -> AgentVerdictArtifact:
        critical = role.criticality == "critical"
        return AgentVerdictArtifact(
            verdict_id=f"{run_id}-{role.role}-{attempt}-fallback",
            council_run_id=run_id,
            role=role.role,
            specialization_key=candidate.specialization_key,
            evidence_bundle_hash=evidence.bundle_hash,
            agent_snapshot_id=f"{run_id}:{role.role}",
            attempt=attempt,
            decision="block" if critical else "abstain",
            severity="block" if critical else "warn",
            confidence=0.0,
            reason_codes=tuple(dict.fromkeys(errors)),
            usage=AgentUsage(latency_ms=latency_ms),
            raw_output_hash=(
                hashlib.sha256(raw_output.encode()).hexdigest() if raw_output else None
            ),
            parse_status="invalid",
        )

    def _reconsider(
        self,
        attempts: list[RoleAttempt],
        policy: CouncilPolicyResult,
        *,
        profile: CouncilProfile,
        run_id: str,
        candidate: TradeCandidateEnvelope,
        evidence: EvidenceBundle,
        ledger: _BudgetLedger,
    ) -> list[RoleAttempt]:
        if not policy.can_synthesize:
            return []
        by_role = {attempt.role: attempt for attempt in attempts if attempt.verdict}
        targets = [by_role.get("bull_thesis"), by_role.get("bear_thesis")]
        if not all(target and target.verdict and target.verdict.claims for target in targets):
            return []
        revisions: list[RoleAttempt] = []
        for target in targets:
            assert target is not None and target.verdict is not None
            role = next(item for item in profile.roles if item.role == target.role)
            if not role.model.enabled or role.role not in self._clients:
                continue
            if not ledger.can_reserve(role, profile):
                revisions.append(
                    self._fallback_attempt(role, run_id, candidate, evidence, "budget_exhausted")
                )
                continue
            claims = [claim.model_dump(mode="json") for claim in target.verdict.claims]
            objections = [
                claim.model_dump(mode="json")
                for other in targets
                if other is not target and other and other.verdict
                for claim in other.verdict.counterevidence
            ]
            payload = {
                "revision": {
                    "validated_claims": claims,
                    "evidence_ids": sorted(
                        {evidence_id for claim in claims for evidence_id in claim["evidence_ids"]}
                    ),
                    "objections": objections,
                }
            }
            request = self._request(
                role,
                run_id=run_id,
                candidate=candidate,
                evidence=evidence,
                attempt=2,
                payload_override=payload,
            )
            call = self._invoke(request)
            revised, errors = self._parse_verdict(role, request, call, evidence)
            if revised is None:
                revised = self._fallback_verdict(
                    role,
                    run_id=run_id,
                    candidate=candidate,
                    evidence=evidence,
                    attempt=2,
                    errors=errors or (call.error or call.status,),
                    latency_ms=call.latency_ms,
                    raw_output=call.raw_output,
                )
            ledger.record(revised, call.raw_output)
            revisions.append(
                RoleAttempt(
                    role.role,
                    2,
                    call.status,
                    request.request_hash,
                    revised,
                    call.raw_output,
                    errors,
                    call.error,
                )
            )
        return revisions

    def _execute_master(
        self,
        role: RoleConfig,
        *,
        profile: CouncilProfile,
        run_id: str,
        candidate: TradeCandidateEnvelope,
        evidence: EvidenceBundle,
        attempts: list[RoleAttempt],
        policy: CouncilPolicyResult,
        ledger: _BudgetLedger,
    ) -> RoleAttempt:
        if not role.model.enabled or role.role not in self._clients:
            return RoleAttempt(
                role.role,
                1,
                "failed",
                "",
                errors=("master_client_unavailable",),
            )
        if not ledger.can_reserve(role, profile):
            return self._fallback_attempt(role, run_id, candidate, evidence, "budget_exhausted")
        verdicts = [
            attempt.verdict.model_dump(mode="json")
            for attempt in attempts
            if attempt.verdict
        ]
        payload = {
            "candidate": project_for_role(candidate, evidence, "master_synthesizer"),
            "policy": policy.model_dump(mode="json"),
            "validated_verdicts": verdicts,
        }
        request = self._request(
            role,
            run_id=run_id,
            candidate=candidate,
            evidence=evidence,
            payload_override=payload,
        )
        call = self._invoke(request)
        ledger.output_tokens += max(1, len(call.raw_output or "") // 4)
        if call.status != "completed" or call.raw_output is None:
            return RoleAttempt(
                role.role,
                1,
                call.status,
                request.request_hash,
                raw_output=call.raw_output,
                errors=(call.error or call.status,),
            )
        return RoleAttempt(
            role.role,
            1,
            call.status,
            request.request_hash,
            raw_output=call.raw_output,
            errors=(),
            error=call.error,
        )

    @staticmethod
    def _decision_from_master(
        attempt: RoleAttempt,
        *,
        candidate: TradeCandidateEnvelope,
        policy: CouncilPolicyResult,
        run_id: str,
        verdict_ids: Iterable[str],
    ) -> CouncilDecisionArtifact:
        if attempt.status != "completed" or attempt.raw_output is None:
            return hold_decision(run_id, policy, attempt.error or "master_call_failed")
        try:
            decision = CouncilDecisionArtifact.model_validate_json(attempt.raw_output)
        except Exception:
            return hold_decision(run_id, policy, "master_schema_invalid")
        errors = validate_master_decision(
            decision,
            verdict_ids=verdict_ids,
        )
        if decision.council_run_id != run_id:
            errors = (*errors, "council_run_mismatch")
        if decision.outcome == "take" and decision.selected_action != candidate.proposed_action:
            errors = (*errors, "master_changed_candidate_action")
        if (
            candidate.proposed_price is not None
            and decision.max_entry_price is not None
            and decision.max_entry_price > candidate.proposed_price
        ):
            errors = (*errors, "master_loosened_price")
        if (
            candidate.proposed_size is not None
            and decision.max_size is not None
            and decision.max_size > candidate.proposed_size
        ):
            errors = (*errors, "master_increased_size")
        return decision if not errors else hold_decision(run_id, policy, ";".join(errors))


def calculate_policy(
    profile: CouncilProfile, verdicts: list[AgentVerdictArtifact | None]
) -> CouncilPolicyResult:
    by_role = {
        verdict.role: verdict
        for verdict in verdicts
        if verdict is not None and verdict.role != "master_synthesizer"
    }
    critical_roles = {
        role.role
        for role in profile.roles
        if role.criticality == "critical" and role.role != "master_synthesizer"
    }
    missing: tuple[AgentRole, ...] = tuple(
        cast(AgentRole, role)
        for role in _ROLE_ORDER
        if role in critical_roles
        and (
            role not in by_role
            or by_role[role] is None
            or by_role[role].parse_status == "invalid"
        )
    )
    vetoes = tuple(
        f"{role}:{','.join(verdict.reason_codes) or verdict.decision}"
        for role, verdict in sorted(by_role.items())
        if role in critical_roles and (verdict.decision == "block" or verdict.severity == "block")
    )
    bull = by_role.get("bull_thesis")
    bear = by_role.get("bear_thesis")
    quorum = bool(
        bull
        and bear
        and bull.parse_status != "invalid"
        and bear.parse_status != "invalid"
        and bull.decision != "abstain"
        and bear.decision != "abstain"
    )
    abstentions: tuple[AgentRole, ...] = tuple(
        cast(AgentRole, role)
        for role in _ROLE_ORDER
        if (verdict := by_role.get(role)) is not None and verdict.decision == "abstain"
    )
    reasons: list[str] = []
    if missing:
        reasons.append("critical_role_incomplete")
    if vetoes:
        reasons.append("critical_veto")
    if not quorum:
        reasons.append("directional_quorum_not_met")
    return CouncilPolicyResult(
        policy_version=f"{profile.profile_id}:{profile.version}:deterministic-v1",
        quorum_met=quorum,
        required_roles_complete=not missing,
        vetoes=vetoes,
        abstentions=abstentions,
        missing_roles=missing,
        reason_codes=tuple(reasons),
    )


def hold_decision(run_id: str, policy: CouncilPolicyResult, reason: str) -> CouncilDecisionArtifact:
    return CouncilDecisionArtifact(
        decision_id=f"{run_id}-decision-hold",
        council_run_id=run_id,
        outcome="hold",
        summary=reason,
        policy=policy,
    )


__all__ = [
    "CouncilCheckpoint",
    "CouncilCoordinator",
    "CouncilRoutingError",
    "CouncilRunResult",
    "RoleAttempt",
    "calculate_policy",
    "hold_decision",
]
