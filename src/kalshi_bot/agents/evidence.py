"""As-of evidence assembly and role-specific projections."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from kalshi_bot.agents.contracts import (
    AgentRole,
    EvidenceBundle,
    EvidenceItem,
    TradeCandidateEnvelope,
)

_FORBIDDEN_KEYS = {
    "broker",
    "broker_client",
    "client",
    "credential",
    "credentials",
    "authorization",
    "order_id",
    "private_key",
    "token",
    "secret",
    "password",
}

_ROLE_KINDS: dict[AgentRole, frozenset[str] | None] = {
    "researcher": None,
    "bull_thesis": None,
    "bear_thesis": None,
    "skeptic": None,
    "execution_liquidity": frozenset(
        {"quote", "orderbook", "liquidity", "fees", "execution"}
    ),
    "rules_settlement": frozenset(
        {"market", "rules", "settlement", "resolution", "event"}
    ),
    "portfolio_risk": frozenset(
        {"portfolio", "risk", "exposure", "position", "drawdown"}
    ),
    "master_synthesizer": None,
}

_DOMAIN_KINDS: dict[str, frozenset[str]] = {
    "prediction": frozenset(
        {
            "asset",
            "cadence",
            "contract",
            "quote",
            "orderbook",
            "spot",
            "brti",
            "strategy",
            "manifest",
        }
    ),
    "perp": frozenset(
        {
            "asset",
            "mark",
            "quote",
            "orderbook",
            "funding",
            "margin",
            "liquidation",
            "discovery",
            "strategy",
        }
    ),
    "sports": frozenset(
        {
            "sport",
            "league",
            "event",
            "market",
            "rules",
            "settlement",
            "odds",
            "quote",
            "flow",
            "evidence",
            "feasibility",
        }
    ),
}


def _candidate_from_mapping(
    raw: Mapping[str, Any],
    *,
    domain: str,
    specialization_key: str,
    action: str,
) -> TradeCandidateEnvelope:
    """Normalize the small common subset emitted by domain strategies."""

    return TradeCandidateEnvelope(
        candidate_id=str(raw["candidate_id"]),
        domain=domain,  # type: ignore[arg-type]
        specialization_key=specialization_key,
        instrument_id=str(raw["instrument_id"]),
        strategy_name=str(raw["strategy_name"]),
        strategy_version=str(raw["strategy_version"]),
        decision_ts=int(raw["decision_ts"]),
        proposed_action=action,  # type: ignore[arg-type]
        proposed_price=(
            float(raw["proposed_price"]) if raw.get("proposed_price") is not None else None
        ),
        proposed_size=(
            float(raw["proposed_size"]) if raw.get("proposed_size") is not None else None
        ),
        horizon_seconds=(
            int(raw["horizon_seconds"]) if raw.get("horizon_seconds") is not None else None
        ),
        settlement_rule_id=(
            str(raw["settlement_rule_id"])
            if raw.get("settlement_rule_id") is not None
            else None
        ),
        evidence_manifest_hash=str(raw["evidence_manifest_hash"]),
    )


def prediction_candidate_from_mapping(
    raw: Mapping[str, Any], *, specialization_key: str, action: str
) -> TradeCandidateEnvelope:
    if action not in {"BUY_YES", "BUY_NO"}:
        raise ValueError("prediction action must be BUY_YES or BUY_NO")
    return _candidate_from_mapping(
        raw, domain="prediction", specialization_key=specialization_key, action=action
    )


def perp_candidate_from_mapping(
    raw: Mapping[str, Any], *, specialization_key: str, action: str
) -> TradeCandidateEnvelope:
    if action not in {"LONG", "SHORT"}:
        raise ValueError("perp action must be LONG or SHORT")
    return _candidate_from_mapping(
        raw, domain="perp", specialization_key=specialization_key, action=action
    )


def sports_candidate_from_mapping(
    raw: Mapping[str, Any], *, specialization_key: str, action: str
) -> TradeCandidateEnvelope:
    if action not in {"BUY_YES", "BUY_NO"}:
        raise ValueError("sports action must be BUY_YES or BUY_NO")
    return _candidate_from_mapping(
        raw, domain="sports", specialization_key=specialization_key, action=action
    )


def _is_forbidden_key(key: str) -> bool:
    lowered = key.casefold()
    return lowered in _FORBIDDEN_KEYS or any(
        part in lowered for part in ("credential", "private_key")
    )


def _safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _safe_value(item)
            for key, item in value.items()
            if not _is_forbidden_key(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return None


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _item_from_mapping(raw: Mapping[str, Any], *, index: int) -> EvidenceItem:
    source = str(raw.get("source", "")).strip()
    kind = str(raw.get("kind", "")).strip()
    claim = str(raw.get("claim", "")).strip()
    observed_at = raw.get("observed_at")
    available_at = raw.get("available_at")
    if not source or not kind or not claim:
        raise ValueError(f"item {index} is missing source, kind, or claim")
    if not isinstance(observed_at, int) or not isinstance(available_at, int):
        raise ValueError(f"item {index} is missing integer timestamps")
    payload = _safe_value(raw.get("payload", {}))
    if not isinstance(payload, dict):
        payload = {}
    evidence_id = str(raw.get("evidence_id") or "").strip()
    if not evidence_id:
        identity = {
            "source": source,
            "kind": kind,
            "claim": claim,
            "payload": payload,
        }
        evidence_id = f"e-{_canonical_hash(identity)[:24]}"
    content_hash = str(raw.get("content_hash") or _canonical_hash(payload))
    return EvidenceItem(
        evidence_id=evidence_id,
        source=source,
        kind=kind,
        observed_at=observed_at,
        available_at=available_at,
        content_hash=content_hash,
        claim=claim,
        payload=payload,
    )


def build_evidence_bundle(
    candidate: TradeCandidateEnvelope,
    raw_items: Iterable[Mapping[str, Any]],
    *,
    bundle_id: str,
    missing_fields: Iterable[str] = (),
    conflict_fields: Iterable[str] = (),
) -> EvidenceBundle:
    """Freeze eligible records and retain deterministic exclusion reasons."""

    items: list[EvidenceItem] = []
    excluded: list[str] = []
    for index, raw in enumerate(raw_items):
        try:
            item = _item_from_mapping(raw, index=index)
        except ValueError as exc:
            excluded.append(f"item-{index}:invalid:{exc}")
            continue
        if item.available_at > candidate.decision_ts:
            excluded.append(f"{item.evidence_id}:after_decision_ts")
            continue
        items.append(item)

    provisional = EvidenceBundle(
        bundle_id=bundle_id,
        candidate_id=candidate.candidate_id,
        domain=candidate.domain,
        decision_ts=candidate.decision_ts,
        items=tuple(items),
        missing_fields=tuple(sorted(set(missing_fields))),
        conflict_fields=tuple(sorted(set(conflict_fields))),
        excluded_items=tuple(excluded),
        bundle_hash="pending",
    )
    return provisional.model_copy(update={"bundle_hash": provisional.computed_hash()})


def project_domain_evidence(bundle: EvidenceBundle, domain: str) -> tuple[EvidenceItem, ...]:
    """Keep only kinds registered for a domain; unknown kinds stay auditable."""

    if bundle.domain != domain:
        return ()
    kinds = _DOMAIN_KINDS.get(domain)
    if kinds is None:
        return ()
    return tuple(item for item in bundle.items if item.kind in kinds)


def project_prediction_evidence(bundle: EvidenceBundle) -> tuple[EvidenceItem, ...]:
    return project_domain_evidence(bundle, "prediction")


def project_perp_evidence(bundle: EvidenceBundle) -> tuple[EvidenceItem, ...]:
    return project_domain_evidence(bundle, "perp")


def project_sports_evidence(bundle: EvidenceBundle) -> tuple[EvidenceItem, ...]:
    return project_domain_evidence(bundle, "sports")


def project_for_role(
    candidate: TradeCandidateEnvelope,
    bundle: EvidenceBundle,
    role: AgentRole,
) -> dict[str, Any]:
    """Build a JSON-safe minimum projection for one role."""

    kinds = _ROLE_KINDS[role]
    items = (
        bundle.items
        if kinds is None
        else tuple(item for item in bundle.items if item.kind in kinds)
    )
    projected = {
        "candidate": {
            "candidate_id": candidate.candidate_id,
            "domain": candidate.domain,
            "specialization_key": candidate.specialization_key,
            "instrument_id": candidate.instrument_id,
            "strategy_name": candidate.strategy_name,
            "strategy_version": candidate.strategy_version,
            "decision_ts": candidate.decision_ts,
            "proposed_action": candidate.proposed_action,
            "proposed_price": candidate.proposed_price,
            "proposed_size": candidate.proposed_size,
            "horizon_seconds": candidate.horizon_seconds,
            "settlement_rule_id": candidate.settlement_rule_id,
        },
        "evidence_bundle_hash": bundle.bundle_hash,
        "items": [item.model_dump(mode="json") for item in items],
        "missing_fields": list(bundle.missing_fields),
        "conflict_fields": list(bundle.conflict_fields),
        "excluded_items": list(bundle.excluded_items),
    }
    return _safe_value(projected)


__all__ = [
    "build_evidence_bundle",
    "perp_candidate_from_mapping",
    "prediction_candidate_from_mapping",
    "project_domain_evidence",
    "project_for_role",
    "project_perp_evidence",
    "project_prediction_evidence",
    "project_sports_evidence",
    "sports_candidate_from_mapping",
]
