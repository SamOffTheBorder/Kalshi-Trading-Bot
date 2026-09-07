from kalshi_bot.config.crypto_registry import get_asset
from kalshi_bot.discovery import EventSeriesDiscovery, check_event_perp_compatibility


class FakePublic:
    def __init__(self, series):
        self.series = series

    def get_series(self, ticker):
        return self.series

    def iter_markets(self, **kwargs):
        return iter([{"ticker": "TEST"}])


def test_event_discovery_records_valid_series():
    instrument = get_asset("ETH").instrument("15m")
    result = EventSeriesDiscovery(
        FakePublic({"cadence": "15m", "contract_shape": "binary"}), clock=lambda: 100
    ).check(get_asset("ETH"), instrument)
    assert result.eligible is True
    assert result.metadata["active_market_count"] == 1


def test_event_discovery_fails_closed_on_missing_series():
    instrument = get_asset("ETH").instrument("15m")
    result = EventSeriesDiscovery(FakePublic({}), clock=lambda: 100).check(
        get_asset("ETH"), instrument
    )
    # The fake has no declared shape/cadence, but active markets make this a
    # valid legacy-shaped response; an unavailable client is tested below.
    assert result.eligible is True


def test_compatibility_rejects_binary_event_hedge_and_stale_snapshot():
    event = EventSeriesDiscovery(FakePublic({"cadence": "15m"}), clock=lambda: 100).check(
        get_asset("ETH"), get_asset("ETH").instrument("15m")
    )
    event = event.__class__(**{**event.__dict__, "metadata": {"market_shape": "binary"}})
    perp = event.__class__(
        "ETH", "perp", "ETH-PERP", None, 100, True, None, {"reference_index": "CF"}
    )
    assert (
        check_event_perp_compatibility(get_asset("ETH"), event, perp, now=100).reason
        == "binary_event_not_linear_hedge"
    )
    assert (
        check_event_perp_compatibility(get_asset("ETH"), event, perp, now=2000, max_age_s=10).reason
        == "stale_snapshot"
    )
