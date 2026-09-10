"""Conservative classification of Kalshi sports contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RejectionReason(StrEnum):
    FUTURES = "futures_not_supported"
    PLAYER_PROP = "player_prop_not_supported"
    COMBO = "combo_not_supported"
    MULTI_OUTCOME = "multi_outcome_not_supported"
    UNKNOWN_RULES = "unknown_rules"
    INVALID_METADATA = "invalid_metadata"
    NOT_SPORTS = "not_sports"
    NOT_LIQUID = "not_currently_tradeable"


@dataclass(frozen=True)
class Classification:
    eligible: bool
    outcome_shape: str | None
    sport: str | None
    reason: str | None = None
    settlement_source: str | None = None


def _text(raw: dict[str, Any], *keys: str) -> str:
    return " ".join(str(raw.get(k) or "") for k in keys).lower()


def _outcomes(raw: dict[str, Any]) -> list[Any] | None:
    for key in ("outcomes", "outcome", "contracts"):
        value = raw.get(key)
        if isinstance(value, list):
            return value
    return None


def classify_market(raw: dict[str, Any], *, series: dict[str, Any] | None = None) -> Classification:
    """Return an explicit, conservative classification for one market.

    Metadata is intentionally rejected when it cannot prove a binary game
    contract. This prevents a high-volume but semantically ambiguous market
    from entering capture or validation by accident.
    """
    series = series or {}
    # Kalshi market payloads carry no sport/category field at all; the series is
    # the only place the classification is stated, and it states it as
    # `category: "Sports"` (with the league in `tags`). Reading only the market
    # rejected every real game contract as not_sports.
    sport = (
        str(
            raw.get("sport")
            or raw.get("category")
            or series.get("sport")
            or series.get("category")
            or ""
        ).strip()
        or None
    )
    if sport is None or sport.lower() not in {
        "sports",
        "sport",
        "nfl",
        "nba",
        "wnba",
        "nhl",
        "mlb",
        "ncaa",
        "soccer",
        "tennis",
        "football",
        "basketball",
        "baseball",
        "hockey",
    }:
        return Classification(False, None, sport, RejectionReason.NOT_SPORTS)
    if not raw.get("ticker") or not raw.get("event_ticker"):
        return Classification(False, None, sport, RejectionReason.INVALID_METADATA)
    text = _text(raw, "title", "subtitle", "ticker", "event_ticker", "market_type", "category")
    if any(token in text for token in ("parlay", "combo", "same game", "multi-leg", "multileg")):
        return Classification(False, None, sport, RejectionReason.COMBO)
    if any(token in text for token in ("player", "points", "yards", "goals", "touchdown", "prop")):
        return Classification(False, None, sport, RejectionReason.PLAYER_PROP)
    if any(token in text for token in ("season", "champion", "win total", "futures", "playoffs")):
        return Classification(False, None, sport, RejectionReason.FUTURES)
    declared = str(
        raw.get("outcome_shape")
        or raw.get("market_shape")
        or raw.get("contract_shape")
        or series.get("market_shape")
        or ""
    ).lower()
    outcomes = _outcomes(raw)
    if outcomes is not None and len(outcomes) != 2:
        return Classification(False, "multi_outcome", sport, RejectionReason.MULTI_OUTCOME)
    if declared and declared not in {
        "binary",
        "yes_no",
        "two_outcome",
        "moneyline",
        "spread",
        "single_game",
    }:
        return Classification(False, declared, sport, RejectionReason.MULTI_OUTCOME)
    settlement = (
        raw.get("settlement_source") or raw.get("settlement_source_url") or raw.get("rules_primary")
    )
    if not settlement:
        return Classification(
            False, "binary" if declared else None, sport, RejectionReason.UNKNOWN_RULES
        )
    if raw.get("event_ticker") == raw.get("ticker"):
        return Classification(False, "binary", sport, RejectionReason.INVALID_METADATA)
    return Classification(True, "binary", sport, None, str(settlement))
