from kalshi_bot.backtest.perp_ledger import build_perp_report


def test_perp_report_is_domain_separated_and_includes_promotion_verdict():
    report = build_perp_report([], coverage={"asset": "BTC", "rows": 0})
    assert report["domain"] == "perp"
    assert report["coverage"]["asset"] == "BTC"
    assert report["promotion"]["passed"] is False
