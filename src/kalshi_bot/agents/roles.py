"""Compatibility adapters for existing narrow AI roles."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from kalshi_bot.agents.contracts import (
    AgentUsage,
    AgentVerdictArtifact,
    EvidenceClaim,
    TradeCandidateEnvelope,
)
from kalshi_bot.ai.local_review import (
    LocalReviewClient,
    TradeCandidate,
    VetoVerdict,
    to_veto_verdict_record,
)
from kalshi_bot.ai.sports_research import EvidenceSummary


@dataclass(frozen=True)
class LocalReviewRoleResult:
    verdict: AgentVerdictArtifact
    legacy_verdict: VetoVerdict

    @property
    def legacy_record(self) -> object:
        return to_veto_verdict_record(self.legacy_verdict, model="legacy-local-review")


class LocalReviewSkepticRole:
    """Map the existing fail-closed veto into the council artifact contract."""

    def __init__(
        self,
        client: LocalReviewClient,
        *,
        council_run_id: str,
        evidence_bundle_hash: str,
        agent_snapshot_id: str,
    ) -> None:
        self._client = client
        self._council_run_id = council_run_id
        self._evidence_bundle_hash = evidence_bundle_hash
        self._agent_snapshot_id = agent_snapshot_id

    def review(self, candidate: TradeCandidateEnvelope) -> LocalReviewRoleResult:
        if candidate.domain != "prediction":
            legacy = VetoVerdict(False, "legacy_review_supports_prediction_only")
        else:
            legacy = self._client.review(
                TradeCandidate(
                    market_ticker=candidate.instrument_id,
                    strategy_name=candidate.strategy_name,
                    action=candidate.proposed_action,
                    entry_price_cents=int(candidate.proposed_price or 0),
                    fee_adjusted_edge=None,
                    confidence=None,
                    minutes_to_expiry=(candidate.horizon_seconds or 0) / 60,
                )
            )
        raw_hash = (
            hashlib.sha256(legacy.raw_response.encode()).hexdigest()
            if legacy.raw_response is not None
            else None
        )
        verdict = AgentVerdictArtifact(
            verdict_id=f"legacy-{self._council_run_id}-skeptic",
            council_run_id=self._council_run_id,
            role="skeptic",
            specialization_key=candidate.specialization_key,
            evidence_bundle_hash=self._evidence_bundle_hash,
            agent_snapshot_id=self._agent_snapshot_id,
            decision="support" if legacy.approved else "block",
            severity="info" if legacy.approved else "block",
            confidence=legacy.confidence or 0.0,
            reason_codes=("legacy_veto_approved" if legacy.approved else "legacy_veto_rejected",),
            usage=AgentUsage(latency_ms=legacy.latency_ms),
            raw_output_hash=raw_hash,
        )
        return LocalReviewRoleResult(verdict, legacy)


def sports_research_to_verdict(
    summary: EvidenceSummary,
    *,
    council_run_id: str,
    specialization_key: str,
    evidence_bundle_hash: str,
    agent_snapshot_id: str,
    evidence_ids: tuple[str, ...],
) -> AgentVerdictArtifact:
    decision = {
        "supportive": "support",
        "adverse": "oppose",
        "mixed": "abstain",
        "unknown": "abstain",
    }.get(summary.classification or "unknown", "abstain")
    severity = "info" if summary.available else "warn"
    claims = (
        (
            EvidenceClaim(
                claim=summary.summary or summary.status,
                evidence_ids=evidence_ids,
                strength=1.0,
            ),
        )
        if evidence_ids
        else ()
    )
    return AgentVerdictArtifact(
        verdict_id=f"sports-research-{summary.market_ticker}-{summary.retrieved_at}",
        council_run_id=council_run_id,
        role="researcher",
        specialization_key=specialization_key,
        evidence_bundle_hash=evidence_bundle_hash,
        agent_snapshot_id=agent_snapshot_id,
        decision=decision,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        confidence=1.0 if summary.available else 0.0,
        claims=claims,
        reason_codes=(summary.status,),
        usage=AgentUsage(latency_ms=summary.latency_ms),
        raw_output_hash=summary.output_hash,
    )


__all__ = ["LocalReviewRoleResult", "LocalReviewSkepticRole", "sports_research_to_verdict"]
