from kalshi_bot.data.sports.validation import FeasibilityReport, evaluate_sports_paper_admission


def _report(outcome: str) -> FeasibilityReport:
    return FeasibilityReport(outcome, 100, 10, 5, 5, 1.0, 0.1, 0.2)


def test_sports_admission_requires_research_and_operator_ack():
    assert (
        evaluate_sports_paper_admission(
            _report("insufficient_data"),
            rules_verified=True,
            provider_evidence=True,
            fresh_data=True,
            liquid_quote=True,
            strategy_version="s1",
            operator_acknowledged=True,
        ).reason
        == "research_not_promising"
    )
    assert (
        evaluate_sports_paper_admission(
            _report("research_promising"),
            rules_verified=True,
            provider_evidence=True,
            fresh_data=True,
            liquid_quote=True,
            strategy_version="s1",
            operator_acknowledged=False,
        ).reason
        == "operator_ack_required"
    )


def test_sports_admission_passes_only_when_all_prerequisites_hold():
    result = evaluate_sports_paper_admission(
        _report("research_promising"),
        rules_verified=True,
        provider_evidence=True,
        fresh_data=True,
        liquid_quote=True,
        strategy_version="s1",
        operator_acknowledged=True,
    )
    assert result.admitted is True
