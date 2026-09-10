"""Fail-closed local/hosted LLM research adapters for sports evidence."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from kalshi_bot.data.sports.evidence import EvidenceCard, SourceAllowlist, eligible_cards
from kalshi_bot.storage import SportsLLMReview

REVIEW_SYSTEM_PROMPT = (
    "Summarize only the supplied point-in-time evidence. Do not invent facts "
    "or markets, and do not propose trades. Return JSON: "
    '{"summary": string, "classification": "supportive"|"adverse"|"mixed"|'
    '"unknown", "citations": [string]}'
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceSummary:
    market_ticker: str
    provider: str
    model: str
    summary: str | None
    classification: str | None
    citations: tuple[str, ...] = ()
    prompt_hash: str = ""
    output_hash: str | None = None
    available: bool = False
    status: str = "unavailable"
    latency_ms: int | None = None
    raw_output: str | None = None
    retrieved_at: int = 0
    provenance: dict = field(default_factory=dict)

    def as_model(self) -> SportsLLMReview:
        return SportsLLMReview(
            market_ticker=self.market_ticker,
            provider=self.provider,
            model=self.model,
            prompt_hash=self.prompt_hash,
            output_hash=self.output_hash,
            citations=list(self.citations),
            summary=self.summary,
            classification=self.classification,
            available_at=self.retrieved_at,
            retrieved_at=self.retrieved_at,
            latency_ms=self.latency_ms,
            status=self.status,
            raw_output=self.raw_output,
            provenance=self.provenance,
        )


def _payload(market_ticker: str, cards: Iterable[EvidenceCard], decision_ts: int) -> str:
    rows = [
        {
            "provider": c.provider,
            "url": c.endpoint_url,
            "claim": c.claim,
            "publication_at": c.publication_at,
            "observed_at": c.observed_at,
            "available_at": c.available_at,
            "hash": c.raw_content_hash,
            "raw": c.raw_content[:2_000],
        }
        for c in eligible_cards(cards, decision_ts=decision_ts)
    ]
    return json.dumps(
        {"market_ticker": market_ticker, "decision_ts": decision_ts, "evidence": rows},
        sort_keys=True,
    )


def _parse_summary(
    content: str,
    *,
    market_ticker: str,
    provider: str,
    model: str,
    prompt_hash: str,
    latency_ms: int,
    retrieved_at: int,
) -> EvidenceSummary:
    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("summary"), str):
            raise ValueError("unexpected_shape")
        classification = parsed.get("classification")
        if classification not in {"supportive", "adverse", "mixed", "unknown"}:
            raise ValueError("invalid_classification")
        citations = parsed.get("citations", [])
        if not isinstance(citations, list) or not all(isinstance(x, str) for x in citations):
            raise ValueError("invalid_citations")
        return EvidenceSummary(
            market_ticker,
            provider,
            model,
            parsed["summary"],
            classification,
            tuple(citations),
            prompt_hash,
            _hash(content),
            True,
            "ok",
            latency_ms,
            content,
            retrieved_at,
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        return EvidenceSummary(
            market_ticker,
            provider,
            model,
            None,
            None,
            (),
            prompt_hash,
            _hash(content),
            False,
            "malformed_output",
            latency_ms,
            content,
            retrieved_at,
        )


class LocalOllamaEvidenceReviewer:
    provider = "ollama"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3:14b",
        timeout_s: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout_s)

    def close(self) -> None:
        self._client.close()

    def review(
        self, *, market_ticker: str, cards: Iterable[EvidenceCard], decision_ts: int
    ) -> EvidenceSummary:
        prompt = _payload(market_ticker, cards, decision_ts)
        started = time.monotonic()
        try:
            response = self._client.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0},
                },
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content")
            if not isinstance(content, str) or not content:
                raise ValueError("empty_response")
            return _parse_summary(
                content,
                market_ticker=market_ticker,
                provider=self.provider,
                model=self.model,
                prompt_hash=_hash(prompt),
                latency_ms=int((time.monotonic() - started) * 1000),
                retrieved_at=int(time.time()),
            )
        except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return EvidenceSummary(
                market_ticker,
                self.provider,
                self.model,
                None,
                None,
                (),
                _hash(prompt),
                None,
                False,
                f"unavailable:{type(exc).__name__}",
                int((time.monotonic() - started) * 1000),
                None,
                int(time.time()),
            )


class OpenRouterSportsResearch:
    provider = "openrouter"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "openai/gpt-4o-mini",
        allowlist: SourceAllowlist,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_s: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key, self.model, self.allowlist = api_key, model, allowlist
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout_s)

    def close(self) -> None:
        self._client.close()

    def research(
        self,
        *,
        market_ticker: str,
        query: str,
        decision_ts: int,
        max_results: int = 5,
        domains: Iterable[str] = (),
    ) -> EvidenceSummary:
        if not self.api_key or max_results < 1 or max_results > 10:
            return EvidenceSummary(
                market_ticker,
                self.provider,
                self.model,
                None,
                None,
                (),
                "",
                None,
                False,
                "disabled_or_invalid",
                0,
                None,
                int(time.time()),
            )
        requested_domains = tuple(domains)
        if requested_domains and not set(requested_domains).issubset(self.allowlist.domains):
            return EvidenceSummary(
                market_ticker,
                self.provider,
                self.model,
                None,
                None,
                (),
                "",
                None,
                False,
                "domain_not_allowlisted",
                0,
                None,
                int(time.time()),
            )
        prompt = json.dumps(
            {
                "market_ticker": market_ticker,
                "query": query,
                "decision_ts": decision_ts,
                "max_results": max_results,
                "domains": requested_domains,
            },
            sort_keys=True,
        )
        prompt_hash, started = _hash(prompt), time.monotonic()
        try:
            params: dict[str, Any] = {"max_results": max_results}
            if requested_domains:
                params["search_domain_filter"] = list(requested_domains)
            response = self._client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "tools": [{"type": "openrouter:web_search", "parameters": params}],
                    "temperature": 0,
                },
            )
            response.raise_for_status()
            content = response.json().get("choices", [{}])[0].get("message", {}).get("content")
            if not isinstance(content, str) or not content:
                raise ValueError("empty_response")
            summary = _parse_summary(
                content,
                market_ticker=market_ticker,
                provider=self.provider,
                model=self.model,
                prompt_hash=prompt_hash,
                latency_ms=int((time.monotonic() - started) * 1000),
                retrieved_at=int(time.time()),
            )
            citations = tuple(
                url
                for url in summary.citations
                if urlparse(url).scheme in {"http", "https"}
                and any(
                    (urlparse(url).hostname or "").lower() == d
                    or (urlparse(url).hostname or "").lower().endswith("." + d)
                    for d in self.allowlist.domains
                )
            )
            return EvidenceSummary(
                **{
                    **summary.__dict__,
                    "citations": citations,
                    "provenance": {"decision_ts": decision_ts, "temporal_filter": "required"},
                }
            )
        except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return EvidenceSummary(
                market_ticker,
                self.provider,
                self.model,
                None,
                None,
                (),
                prompt_hash,
                None,
                False,
                f"unavailable:{type(exc).__name__}",
                int((time.monotonic() - started) * 1000),
                None,
                int(time.time()),
            )


def persist_review(session: Any, review: EvidenceSummary) -> SportsLLMReview:
    row = review.as_model()
    session.add(row)
    session.flush()
    return row


def require_strategy_candidate(candidate: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not candidate or not candidate.get("strategy_name") or not candidate.get("market_ticker"):
        raise ValueError("strategy_candidate_required")
    return candidate


__all__ = [
    "EvidenceSummary",
    "LocalOllamaEvidenceReviewer",
    "OpenRouterSportsResearch",
    "persist_review",
    "require_strategy_candidate",
]
