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
from kalshi_bot.data.sports.evidence import (
    EvidenceAdapter,
    EvidenceCard,
    SourceAllowlist,
    eligible_cards,
    persist_evidence,
    resolve_conflicts,
    validate_card,
)
from kalshi_bot.data.sports.external import ExternalSportsObservation, ExternalSportsSource
from kalshi_bot.data.sports.flow import (
    FlowFeatureWindow,
    calculate_flow_features,
    copy_trading_status,
    persist_flow_feature,
)
from kalshi_bot.data.sports.validation import (
    CandidateSignal,
    FeasibilityReport,
    FillResult,
    SportsAdmission,
    SportsObservation,
    chronological_evaluation,
    compare_candidate_variants,
    evaluate_sports_paper_admission,
    feasibility_report,
    simulate_fill,
    time_to_event_bucket,
)

__all__ = [
    "CandidateSignal",
    "CaptureResult",
    "Classification",
    "EvidenceAdapter",
    "EvidenceCard",
    "ExternalSportsObservation",
    "ExternalSportsSource",
    "FeasibilityReport",
    "FillResult",
    "FlowFeatureWindow",
    "RejectionReason",
    "SourceAllowlist",
    "SportsAdmission",
    "SportsDiscovery",
    "SportsObservation",
    "calculate_flow_features",
    "capture_report",
    "capture_sports",
    "chronological_evaluation",
    "classify_market",
    "compare_candidate_variants",
    "copy_trading_status",
    "discover_sports",
    "eligible_cards",
    "evaluate_sports_paper_admission",
    "feasibility_report",
    "persist_evidence",
    "persist_flow_feature",
    "record_gaps",
    "resolve_conflicts",
    "simulate_fill",
    "time_to_event_bucket",
    "validate_card",
]
