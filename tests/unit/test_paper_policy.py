from kalshi_bot.risk.paper_policy import RiskPolicy, RiskRequest, admit_risk


def _request(**changes):
    values = dict(
        domain="prediction",
        asset_id="BTC",
        correlation_group="major-crypto",
        market_id="KXBTC",
        worst_case_loss_usd=10,
        data_age_seconds=10,
        reconciled=True,
    )
    values.update(changes)
    return RiskRequest(**values)


def test_cross_domain_risk_policy_blocks_scope_and_freshness():
    assert (
        admit_risk(
            _request(group_exposure_usd=75), RiskPolicy(max_correlation_group_exposure_usd=80)
        ).reason
        == "correlation_group_budget"
    )
    assert admit_risk(_request(data_age_seconds=121)).reason == "stale_required_data"
    assert admit_risk(_request(reconciled=False)).reason == "reconciliation_required"
    assert admit_risk(_request()).allowed is True


def test_risk_policy_blocks_drawdown_daily_and_consecutive_limits():
    assert admit_risk(_request(drawdown_pct=0.10)).reason == "drawdown_limit"
    assert admit_risk(_request(daily_loss_usd=30)).reason == "daily_loss_limit"
    assert admit_risk(_request(consecutive_losses=3)).reason == "consecutive_loss_limit"
