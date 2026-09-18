"""Local pre-trade veto gate via Ollama (tasks.md 7.1, design D5).

D5: "Latency and cost both point local for anything per-trade." This is the
fast-path check that runs on every candidate entry, in contrast to
`ai/openrouter.py` (7.4, not yet built), which is reserved for sparse,
non-latency-critical calls (news retrieval, daily/weekly review).

**Fail-closed is the entire point of this module** (design D5, spec intent):
no response, a malformed response, an HTTP error, or a response that
doesn't parse as the expected JSON verdict shape all mean the SAME thing —
`VetoVerdict(approved=False, reason="...")`. A trading gate that fails open
on a broken LLM integration is worse than no gate at all; this class is
built so there is no code path that returns "approved" except a
successfully parsed, well-formed, explicit approval from the model.

The prompt is intentionally structured and narrow: numbers in, JSON verdict
out, low temperature. This is not a chat interface and never free-texts a
decision — `_build_prompt` gives the model a fixed candidate shape and
`_parse_verdict` accepts only the fixed response shape back.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger

from kalshi_bot.storage.models import VetoVerdictRecord

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:14b"
"""Design D5's recommendation. Callers on a machine with a differently-named
local pull (e.g. an abliterated/quantized variant under another tag) should
override via `LocalReviewClient(model=...)` — this module makes no
assumption about which exact tag is installed beyond the config default."""

VETO_SYSTEM_PROMPT = """You are a pre-trade risk reviewer for an automated \
trading bot. You will be given a proposed trade as structured data. Decide \
whether to APPROVE or REJECT it based solely on the numbers given — do not \
invent information not present in the input.

Respond with ONLY a JSON object of this exact shape, nothing else:
{"approved": true or false, "confidence": a number from 0.0 to 1.0, \
"reason": "one short sentence"}
"""


@dataclass(frozen=True)
class TradeCandidate:
    """The fixed, structured shape of what gets reviewed — deliberately a
    narrow subset of fields, not an open-ended dump of every internal
    strategy variable, so the prompt stays small and reproducible."""

    market_ticker: str
    strategy_name: str
    action: str  # "BUY_YES" | "BUY_NO"
    entry_price_cents: int
    fee_adjusted_edge: float | None
    confidence: float | None
    minutes_to_expiry: float
    trend_zscore: float | None = None


@dataclass(frozen=True)
class VetoVerdict:
    approved: bool
    reason: str
    confidence: float | None = None
    raw_response: str | None = None
    """Full raw model output, kept for `VetoVerdictRecord`-style persistence
    (tasks.md 7.6) even on a parse failure — a rejected verdict due to
    malformed JSON should still leave a record of what the model actually
    said, for later debugging/benchmarking (tasks.md 7.5)."""
    latency_ms: int | None = None
    """Wall-clock time for the request, for tasks.md 7.5's latency
    benchmark. None only when the request never completed enough to time
    (never happens in practice — even a failed request is timed)."""


class LocalReviewClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.1,
        timeout_s: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._temperature = temperature
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout_s)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> LocalReviewClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def review(self, candidate: TradeCandidate) -> VetoVerdict:
        """Fail-closed: ANY problem (network error, non-200, empty body,
        invalid JSON, missing/wrong-typed fields) returns
        `approved=False` — never raises, since a strategy loop calling this
        on the live path must not crash on an LLM hiccup, and must never
        treat a hiccup as silent approval either."""
        prompt = _build_prompt(candidate)
        start = time.monotonic()
        try:
            response = self._client.post(
                "/api/chat",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": VETO_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": self._temperature},
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.warning("LocalReviewClient: request failed, veto fail-closed: {}", exc)
            return VetoVerdict(
                approved=False, reason=f"request_failed:{exc}", latency_ms=latency_ms
            )

        latency_ms = int((time.monotonic() - start) * 1000)
        body: dict[str, Any] = response.json()
        content = body.get("message", {}).get("content")
        if not content:
            logger.warning("LocalReviewClient: empty response content, veto fail-closed")
            return VetoVerdict(approved=False, reason="empty_response", latency_ms=latency_ms)

        return _parse_verdict(content, latency_ms=latency_ms)


def _build_prompt(candidate: TradeCandidate) -> str:
    payload = {
        "market_ticker": candidate.market_ticker,
        "strategy_name": candidate.strategy_name,
        "action": candidate.action,
        "entry_price_cents": candidate.entry_price_cents,
        "fee_adjusted_edge": candidate.fee_adjusted_edge,
        "confidence": candidate.confidence,
        "minutes_to_expiry": candidate.minutes_to_expiry,
        "trend_zscore": candidate.trend_zscore,
    }
    return json.dumps(payload)


def _parse_verdict(content: str, *, latency_ms: int | None = None) -> VetoVerdict:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("LocalReviewClient: malformed JSON, veto fail-closed: {!r}", content[:300])
        return VetoVerdict(
            approved=False, reason="malformed_json", raw_response=content, latency_ms=latency_ms
        )

    if not isinstance(parsed, dict) or "approved" not in parsed:
        logger.warning(
            "LocalReviewClient: unexpected verdict shape, veto fail-closed: {!r}", parsed
        )
        return VetoVerdict(
            approved=False, reason="unexpected_shape", raw_response=content, latency_ms=latency_ms
        )

    approved = parsed.get("approved")
    if not isinstance(approved, bool):
        return VetoVerdict(
            approved=False,
            reason="non_boolean_approved",
            raw_response=content,
            latency_ms=latency_ms,
        )

    reason = parsed.get("reason")
    if not isinstance(reason, str):
        reason = "no_reason_given"

    confidence = parsed.get("confidence")
    if not isinstance(confidence, int | float):
        confidence = None

    return VetoVerdict(
        approved=approved,
        reason=reason,
        confidence=float(confidence) if confidence is not None else None,
        raw_response=content,
        latency_ms=latency_ms,
    )


def to_veto_verdict_record(
    verdict: VetoVerdict, *, model: str, signal_id: int | None = None
) -> VetoVerdictRecord:
    """Build the persistable row for one verdict (tasks.md 7.6). Called
    unconditionally by the caller (approved, rejected, or fail-closed
    alike) — see `VetoVerdictRecord`'s docstring for why every outcome is
    recorded, not just approvals."""
    return VetoVerdictRecord(
        signal_id=signal_id,
        model=model,
        approved=verdict.approved,
        confidence=verdict.confidence,
        reason=verdict.reason,
        raw_response=verdict.raw_response,
        latency_ms=verdict.latency_ms,
    )


__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_OLLAMA_BASE_URL",
    "LocalReviewClient",
    "TradeCandidate",
    "VetoVerdict",
    "to_veto_verdict_record",
]
