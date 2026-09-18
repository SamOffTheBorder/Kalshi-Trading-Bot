"""Explicit, fail-closed discovery for configured event and perp instruments."""

from kalshi_bot.discovery.service import (
    CompatibilityResult,
    DiscoverySnapshot,
    EventSeriesDiscovery,
    PerpDiscovery,
    check_event_perp_compatibility,
    check_source_alignment,
)

__all__ = [
    "CompatibilityResult",
    "DiscoverySnapshot",
    "EventSeriesDiscovery",
    "PerpDiscovery",
    "check_event_perp_compatibility",
    "check_source_alignment",
]
