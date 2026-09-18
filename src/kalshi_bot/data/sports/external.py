"""Opt-in external sports source boundary; no provider is selected here."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ExternalSportsObservation:
    provider: str
    endpoint: str
    observed_at: int
    available_at: int
    value: Any
    provenance: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.provider or not self.endpoint:
            raise ValueError("provider and endpoint are required")
        if self.available_at < self.observed_at:
            raise ValueError("available_at cannot precede observed_at")


class ExternalSportsSource(Protocol):
    provider: str
    endpoint: str

    def fetch(self, *, market_ticker: str, asof_ts: int) -> ExternalSportsObservation: ...
