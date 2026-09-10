"""Opt-in, append-only external sports evidence with temporal safety."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from kalshi_bot.storage import SportsEvidenceCard


@dataclass(frozen=True)
class SourceAllowlist:
    providers: frozenset[str] = frozenset()
    domains: frozenset[str] = frozenset()
    max_requests_per_minute: int = 30

    def rate_limit_allows(self, request_times: Iterable[int], *, now: int) -> bool:
        """Pure rate-limit check for an adapter-owned request ledger."""
        recent = sum(1 for timestamp in request_times if now - int(timestamp) < 60)
        return recent < self.max_requests_per_minute

    def permits(self, provider: str, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return provider in self.providers and any(
            host == d or host.endswith("." + d) for d in self.domains
        )


@dataclass(frozen=True)
class EvidenceCard:
    market_ticker: str
    provider: str
    endpoint_url: str
    claim: str
    publication_at: int | None = None
    observed_at: int | None = None
    available_at: int = 0
    retrieved_at: int = 0
    raw_content: str = ""
    evidence_version: str = "evidence-v1"
    series_ticker: str | None = None
    citations: tuple[str, ...] = ()
    status: str = "usable"
    provenance: dict = field(default_factory=dict)

    @property
    def raw_content_hash(self) -> str:
        return hashlib.sha256(self.raw_content.encode("utf-8")).hexdigest()

    @property
    def causal_at(self) -> int | None:
        return self.publication_at if self.publication_at is not None else self.observed_at

    def temporal_eligible(self, decision_ts: int) -> bool:
        causal = self.causal_at
        return (
            self.status == "usable"
            and causal is not None
            and causal <= decision_ts
            and self.available_at <= decision_ts
        )

    def as_model(self) -> SportsEvidenceCard:
        return SportsEvidenceCard(
            series_ticker=self.series_ticker,
            market_ticker=self.market_ticker,
            provider=self.provider,
            endpoint_url=self.endpoint_url,
            claim=self.claim,
            observed_at=self.observed_at,
            publication_at=self.publication_at,
            available_at=self.available_at,
            retrieved_at=self.retrieved_at,
            raw_content_hash=self.raw_content_hash,
            evidence_version=self.evidence_version,
            source_domain=urlparse(self.endpoint_url).hostname,
            citations=list(self.citations),
            raw_content=self.raw_content,
            status=self.status,
            provenance=self.provenance,
        )


class EvidenceAdapter(Protocol):
    provider: str
    endpoint_url: str

    def fetch(self, *, market_ticker: str, asof_ts: int) -> Iterable[EvidenceCard]: ...


def validate_card(card: EvidenceCard, allowlist: SourceAllowlist) -> EvidenceCard:
    """Validate source policy and timing without replacing or interpolating data."""
    status = card.status
    reason = None
    if not allowlist.permits(card.provider, card.endpoint_url):
        status, reason = "disallowed_source", "source_not_allowlisted"
    elif card.causal_at is None:
        status, reason = "unusable", "missing_causal_timestamp"
    elif card.available_at < 0 or card.retrieved_at < card.available_at:
        status, reason = "unusable", "invalid_availability_timestamps"
    provenance = {**card.provenance, **({"rejection_reason": reason} if reason else {})}
    return EvidenceCard(**{**card.__dict__, "status": status, "provenance": provenance})


def eligible_cards(cards: Iterable[EvidenceCard], *, decision_ts: int) -> list[EvidenceCard]:
    """Return only cards available and published/observed by the decision."""
    return [card for card in cards if card.temporal_eligible(decision_ts)]


def resolve_conflicts(
    cards: Iterable[EvidenceCard], *, decision_ts: int
) -> dict[str, list[EvidenceCard]]:
    """Group eligible claims; conflicting versions remain visible to callers."""
    grouped: dict[str, list[EvidenceCard]] = {}
    for card in eligible_cards(cards, decision_ts=decision_ts):
        grouped.setdefault(card.claim, []).append(card)
    return grouped


def persist_evidence(
    session: Session, card: EvidenceCard, *, allowlist: SourceAllowlist
) -> SportsEvidenceCard:
    checked = validate_card(card, allowlist)
    row = checked.as_model()
    session.add(row)
    session.flush()
    return row


def make_card(
    *,
    market_ticker: str,
    provider: str,
    endpoint_url: str,
    claim: str,
    raw_content: str,
    publication_at: int | None = None,
    observed_at: int | None = None,
    available_at: int | None = None,
    retrieved_at: int | None = None,
    **kwargs,
) -> EvidenceCard:
    now = int(time.time())
    return EvidenceCard(
        market_ticker=market_ticker,
        provider=provider,
        endpoint_url=endpoint_url,
        claim=claim,
        raw_content=raw_content,
        publication_at=publication_at,
        observed_at=observed_at,
        available_at=now if available_at is None else available_at,
        retrieved_at=now if retrieved_at is None else retrieved_at,
        **kwargs,
    )


__all__ = [
    "EvidenceAdapter",
    "EvidenceCard",
    "SourceAllowlist",
    "eligible_cards",
    "make_card",
    "persist_evidence",
    "resolve_conflicts",
    "validate_card",
]
