import pytest

from kalshi_bot.agents.prerequisites import (
    PerpPrerequisites,
    SportsPrerequisites,
    require_perp_profile,
    require_sports_profile,
)


def test_perp_directional_and_funding_carry_route_to_separate_profiles():
    prerequisites = PerpPrerequisites(True, True, True, True, True)
    assert require_perp_profile("perp/BTC/directional", prerequisites).profile_id == (
        "perp-btc-directional"
    )
    assert require_perp_profile("perp/BTC/funding-carry", prerequisites).profile_id == (
        "perp-btc-funding-carry"
    )


def test_perp_missing_real_data_stays_below_profile_influence():
    prerequisites = PerpPrerequisites(True, True, False, True, True)
    with pytest.raises(ValueError, match="perp prerequisites"):
        require_perp_profile("perp/BTC/directional", prerequisites)


def test_sports_requires_narrow_feasibility_report_and_operator_ack():
    incomplete = SportsPrerequisites("report", "research_promising", True, True, True, False)
    with pytest.raises(ValueError, match="sports feasibility"):
        require_sports_profile("sports/NFL/game/moneyline", incomplete)
    complete = SportsPrerequisites("report", "research_promising", True, True, True, True)
    assert require_sports_profile("sports/NFL/game/moneyline", complete).domain == "sports"
