"""Domain-neutral, serializable audit envelopes for paper operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

AuditKind = Literal[
    "run",
    "decision",
    "risk",
    "data_reference",
    "order_attempt",
    "fill",
    "position",
    "heartbeat",
    "reconciliation",
    "report",
]


@dataclass(frozen=True)
class PaperAuditEnvelope:
    paper_run_id: str
    kind: AuditKind
    domain: Literal["prediction", "perp", "sports"]
    asset_id: str | None
    observed_at: int
    status: str
    reason: str | None = None
    data_manifest_hash: str | None = None
    risk_policy_version: str | None = None
    payload: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


__all__ = ["AuditKind", "PaperAuditEnvelope"]
