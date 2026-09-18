"""Explicit, append-only lifecycle promotion for council profiles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.agents.profiles import ProfileLifecycle
from kalshi_bot.storage.models import CouncilProfileLifecycleRecord

_ORDER: dict[ProfileLifecycle, int] = {
    "disabled": 0,
    "fixture": 1,
    "replay": 2,
    "shadow": 3,
    "paper_advisory": 4,
    "paper_council": 5,
}


@dataclass(frozen=True)
class PromotionReport:
    report_id: str
    profile_id: str
    profile_version: str
    frozen: bool
    registered_at: int
    heldout_completed_at: int
    gate_results: dict[str, bool] = field(default_factory=dict)

    def eligible(self) -> bool:
        return (
            self.frozen
            and self.report_id != ""
            and self.profile_id != ""
            and self.profile_version != ""
            and self.registered_at < self.heldout_completed_at
            and bool(self.gate_results)
            and all(self.gate_results.values())
        )


class ProfilePromotionRefusedError(RuntimeError):
    """Raised when an explicit promotion lacks frozen evidence."""


@dataclass
class CouncilLifecycleStore:
    session: Session
    now_fn: Callable[[], int]
    default_state: ProfileLifecycle = "disabled"

    def current_state(self, profile_id: str) -> ProfileLifecycle:
        row = self.session.execute(
            select(CouncilProfileLifecycleRecord)
            .where(CouncilProfileLifecycleRecord.profile_id == profile_id)
            .order_by(CouncilProfileLifecycleRecord.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return self.default_state
        return row.to_state  # type: ignore[return-value]

    def promote(
        self,
        *,
        profile_id: str,
        profile_version: str,
        to_state: ProfileLifecycle,
        operator: str,
        report: PromotionReport,
    ) -> ProfileLifecycle:
        current = self.current_state(profile_id)
        if not operator.strip():
            raise ProfilePromotionRefusedError("explicit operator is required")
        if report.profile_id != profile_id or report.profile_version != profile_version:
            raise ProfilePromotionRefusedError(
                "promotion report is for a different profile version"
            )
        if not report.eligible():
            raise ProfilePromotionRefusedError("promotion requires a frozen passing report")
        if to_state not in _ORDER:
            raise ProfilePromotionRefusedError(f"unsupported profile lifecycle: {to_state}")
        if _ORDER[to_state] - _ORDER[current] != 1:
            raise ProfilePromotionRefusedError("profile promotion must advance exactly one state")
        self.session.add(
            CouncilProfileLifecycleRecord(
                profile_id=profile_id,
                profile_version=profile_version,
                direction="promote",
                from_state=current,
                to_state=to_state,
                operator=operator,
                report_id=report.report_id,
                reason="frozen promotion report passed",
                gate_results=dict(report.gate_results),
                created_at=self.now_fn(),
            )
        )
        self.session.flush()
        return to_state

    def demote(
        self,
        *,
        profile_id: str,
        profile_version: str,
        to_state: ProfileLifecycle,
        reason: str,
        operator: str | None = None,
    ) -> ProfileLifecycle:
        current = self.current_state(profile_id)
        if to_state not in _ORDER or _ORDER[to_state] >= _ORDER[current]:
            raise ProfilePromotionRefusedError("demotion must move to an earlier lifecycle state")
        self.session.add(
            CouncilProfileLifecycleRecord(
                profile_id=profile_id,
                profile_version=profile_version,
                direction="demote",
                from_state=current,
                to_state=to_state,
                operator=operator,
                reason=reason,
                gate_results={},
                created_at=self.now_fn(),
            )
        )
        self.session.flush()
        return to_state

    def history(self, profile_id: str) -> list[CouncilProfileLifecycleRecord]:
        return list(
            self.session.execute(
                select(CouncilProfileLifecycleRecord)
                .where(CouncilProfileLifecycleRecord.profile_id == profile_id)
                .order_by(CouncilProfileLifecycleRecord.id.asc())
            ).scalars()
        )


__all__ = [
    "CouncilLifecycleStore",
    "ProfilePromotionRefusedError",
    "PromotionReport",
]
