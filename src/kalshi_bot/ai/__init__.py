"""AI layer (tasks.md §7): local pre-trade veto (fast path), OpenRouter
(slow path, sparse/non-latency-critical calls only). See design.md D5."""

from kalshi_bot.ai.sports_research import (
    EvidenceSummary,
    LocalOllamaEvidenceReviewer,
    OpenRouterSportsResearch,
    persist_review,
    require_strategy_candidate,
)

__all__ = [
    "EvidenceSummary",
    "LocalOllamaEvidenceReviewer",
    "OpenRouterSportsResearch",
    "persist_review",
    "require_strategy_candidate",
]
