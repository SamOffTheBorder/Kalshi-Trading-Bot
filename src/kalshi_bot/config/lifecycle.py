"""Explicit lifecycle and identity primitives shared by domains."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LifecycleState = Literal["disabled", "observe", "backtest", "shadow", "paper", "blocked"]
Domain = Literal["prediction", "perp", "sports"]


@dataclass(frozen=True)
class AssetDomainCandidate:
    """Stable identity for a strategy candidate's lifecycle and audit rows."""

    asset: str
    domain: Domain
    candidate: str

    def __post_init__(self) -> None:
        if not self.asset or self.asset.upper() != self.asset:
            raise ValueError("asset must be a non-empty uppercase symbol")
        if not self.candidate or any(ch.isspace() for ch in self.candidate):
            raise ValueError("candidate must be a non-empty whitespace-free name")

    @property
    def key(self) -> str:
        return f"{self.asset}:{self.domain}:{self.candidate}"


def validate_lifecycle(state: str) -> LifecycleState:
    if state not in {"disabled", "observe", "backtest", "shadow", "paper", "blocked"}:
        raise ValueError(f"unsupported lifecycle state: {state!r}")
    return state  # type: ignore[return-value]


__all__ = ["AssetDomainCandidate", "Domain", "LifecycleState", "validate_lifecycle"]
