"""Read-only sports market discovery, capture, and feasibility research."""

from kalshi_bot.data.sports.capture import (
    CaptureResult,
    capture_report,
    capture_sports,
    record_gaps,
)
from kalshi_bot.data.sports.classifier import (
    Classification,
    RejectionReason,
    classify_market,
)
from kalshi_bot.data.sports.discovery import SportsDiscovery, discover_sports
from kalshi_bot.data.sports.external import ExternalSportsObservation, ExternalSportsSource
from kalshi_bot.data.sports.flow import (
    FlowFeatureWindow,
    calculate_flow_features,
    copy_trading_status,
    persist_flow_feature,
)
from kalshi_bot.data.sports.evidence import (
    EvidenceAdapter,
    EvidenceCard,
    SourceAllowlist,
    eligible_cards,
    persist_evidence,
    resolve_conflicts,
    validate_card,
)
from kalshi_bot.data.sports.validation import (
    CandidateSignal,
    FeasibilityReport,
    FillResult,
    SportsObservation,
    chronological_evaluation,
    compare_candidate_variants,
    feasibility_report,
    SportsAdmission,
    evaluate_sports_paper_admission,
    simulate_fill,
    time_to_event_bucket,
)

__all__ = [
    "CandidateSignal",
    "CaptureResult",
    "Classification",
    "ExternalSportsObservation",
    "ExternalSportsSource",
    "EvidenceAdapter",
    "EvidenceCard",
    "FlowFeatureWindow",
    "SourceAllowlist",
    "FeasibilityReport",
    "SportsAdmission",
    "FillResult",
    "RejectionReason",
    "SportsDiscovery",
    "SportsObservation",
    "capture_report",
    "capture_sports",
    "chronological_evaluation",
    "compare_candidate_variants",
    "classify_market",
    "calculate_flow_features",
    "copy_trading_status",
    "eligible_cards",
    "persist_evidence",
    "persist_flow_feature",
    "resolve_conflicts",
    "validate_card",
    "discover_sports",
    "feasibility_report",
    "evaluate_sports_paper_admission",
    "record_gaps",
    "simulate_fill",
    "time_to_event_bucket",
]
