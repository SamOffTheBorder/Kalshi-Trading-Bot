"""Deterministic walls around council recommendations and paper adapters."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from kalshi_bot.agents.contracts import TradeCandidateEnvelope
from kalshi_bot.agents.coordinator import CouncilRunResult

AdmissionMode = Literal["shadow", "paper_advisory", "paper_council"]


@dataclass(frozen=True)
class AdmissionCheck:
    name: str
    passed: bool
    reason: str | None = None


@dataclass(frozen=True)
class AdmissionWallResult:
    allowed: bool
    status: Literal["pass", "hold", "reject"]
    reason_codes: tuple[str, ...] = ()
    checks: tuple[AdmissionCheck, ...] = ()


@dataclass(frozen=True)
class CouncilBoundaryResult:
    status: Literal["shadow_recorded", "hold", "adapter_called"]
    candidate: TradeCandidateEnvelope
    council: CouncilRunResult | None
    adapter_result: object | None = None
    reason_codes: tuple[str, ...] = ()
    stages: tuple[str, ...] = ()


def deterministic_prescreen(
    candidate: TradeCandidateEnvelope,
    checks: Sequence[Callable[[TradeCandidateEnvelope], AdmissionCheck]],
) -> AdmissionWallResult:
    """Run cheap lifecycle/provenance/freshness/safety checks before spending."""

    results = tuple(check(candidate) for check in checks)
    failures = tuple(
        check.reason or check.name for check in results if not check.passed
    )
    return AdmissionWallResult(
        allowed=not failures,
        status="pass" if not failures else "hold",
        reason_codes=failures,
        checks=results,
    )


def _tighten_candidate(
    candidate: TradeCandidateEnvelope,
    *,
    max_entry_price: float | None,
    max_size: float | None,
) -> TradeCandidateEnvelope:
    price = candidate.proposed_price
    if max_entry_price is not None:
        price = max_entry_price if price is None else min(price, max_entry_price)
    size = candidate.proposed_size
    if max_size is not None:
        size = max_size if size is None else min(size, max_size)
    return candidate.model_copy(update={"proposed_price": price, "proposed_size": size})


def validate_council_mode(mode: str) -> AdmissionMode:
    if mode not in {"shadow", "paper_advisory", "paper_council"}:
        raise ValueError("council influence is unavailable for live execution")
    return mode  # type: ignore[return-value]


@dataclass
class CouncilPaperBoundary:
    """Candidate-to-adapter boundary with append-only stage callbacks."""

    mode: AdmissionMode
    pre_checks: tuple[Callable[[TradeCandidateEnvelope], AdmissionCheck], ...] = ()
    final_checks: tuple[Callable[[TradeCandidateEnvelope], AdmissionCheck], ...] = ()
    audit_fn: Callable[[str, dict[str, object]], None] | None = None
    _stages: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        validate_council_mode(self.mode)

    def _audit(self, stage: str, payload: dict[str, object]) -> None:
        self._stages.append(stage)
        if self.audit_fn is not None:
            self.audit_fn(stage, payload)

    def review(
        self,
        candidate: TradeCandidateEnvelope,
        *,
        run_council: Callable[[TradeCandidateEnvelope], CouncilRunResult],
        adapter_fn: Callable[[TradeCandidateEnvelope], object],
    ) -> CouncilBoundaryResult:
        self._stages.clear()
        pre = deterministic_prescreen(candidate, self.pre_checks)
        self._audit("initial_screen", {"allowed": pre.allowed, "reasons": pre.reason_codes})
        if not pre.allowed:
            return CouncilBoundaryResult(
                "hold", candidate, None, reason_codes=pre.reason_codes, stages=tuple(self._stages)
            )

        council = run_council(candidate)
        self._audit(
            "council_recommendation",
            {
                "outcome": council.decision.outcome,
                "decision_id": council.decision.decision_id,
                "policy_version": council.policy.policy_version,
            },
        )
        if self.mode == "shadow":
            return CouncilBoundaryResult(
                "shadow_recorded",
                candidate,
                council,
                reason_codes=("shadow_no_paper_influence",),
                stages=tuple(self._stages),
            )
        if council.decision.outcome != "take":
            return CouncilBoundaryResult(
                "hold",
                candidate,
                council,
                reason_codes=(f"council_{council.decision.outcome}",),
                stages=tuple(self._stages),
            )

        adjusted = _tighten_candidate(
            candidate,
            max_entry_price=council.decision.max_entry_price,
            max_size=council.decision.max_size,
        )
        final = deterministic_prescreen(adjusted, self.final_checks)
        self._audit("final_recheck", {"allowed": final.allowed, "reasons": final.reason_codes})
        if not final.allowed:
            return CouncilBoundaryResult(
                "hold",
                adjusted,
                council,
                reason_codes=final.reason_codes,
                stages=tuple(self._stages),
            )

        adapter_result = adapter_fn(adjusted)
        self._audit("adapter_decision", {"result": str(adapter_result)})
        return CouncilBoundaryResult(
            "adapter_called",
            adjusted,
            council,
            adapter_result=adapter_result,
            stages=tuple(self._stages),
        )


__all__ = [
    "AdmissionCheck",
    "AdmissionMode",
    "AdmissionWallResult",
    "CouncilBoundaryResult",
    "CouncilPaperBoundary",
    "deterministic_prescreen",
    "validate_council_mode",
]
