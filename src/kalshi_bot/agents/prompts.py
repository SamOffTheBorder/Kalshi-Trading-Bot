"""Role mandates for structured, evidence-bound agent calls."""

from __future__ import annotations

import json
from typing import Any

from kalshi_bot.agents.contracts import AgentRole

ROLE_MANDATES: dict[AgentRole, str] = {
    "researcher": (
        "Summarize only supplied current evidence, conflicts, and unknowns; "
        "never propose a trade."
    ),
    "bull_thesis": (
        "Build the strongest case for the candidate action, cite evidence, "
        "and state falsifiers."
    ),
    "bear_thesis": (
        "Build the strongest opposing case, cite evidence, and state what "
        "would invalidate it."
    ),
    "skeptic": (
        "Red-team leakage, stale data, unsupported assumptions, correlation, "
        "and failure modes."
    ),
    "execution_liquidity": (
        "Assess executable quote, spread, depth, fees, slippage, and exit "
        "feasibility."
    ),
    "rules_settlement": (
        "Check instrument identity, wording, resolution source, deadlines, "
        "and side semantics."
    ),
    "portfolio_risk": "Assess exposure, concentration, correlation, drawdown, and scenario loss.",
    "master_synthesizer": (
        "Synthesize validated artifacts while preserving dissent; do not "
        "change deterministic policy."
    ),
}


def build_role_prompt(role: AgentRole, payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "role": role,
            "mandate": ROLE_MANDATES[role],
            "rules": [
                "Use only the supplied evidence and candidate fields.",
                "Cite every substantive claim by evidence ID.",
                "Abstain when required evidence is missing or conflicting.",
                "Return only the configured structured schema.",
            ],
            "payload": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = ["ROLE_MANDATES", "build_role_prompt"]
