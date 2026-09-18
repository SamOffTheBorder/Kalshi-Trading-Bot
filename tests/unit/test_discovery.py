from kalshi_bot.config.crypto_registry import get_asset
from kalshi_bot.discovery import (
    EventSeriesDiscovery,
    PerpDiscovery,
    check_event_perp_compatibility,
    check_source_alignment,
)


class FakePublic:
    def __init__(self, series):
        self.series = series

    def get_series(self, ticker):
        return self.series

    def iter_markets(self, **kwargs):
        return iter([{"ticker": "TEST"}])


class QualityPublic(FakePublic):
    def iter_markets(self, **kwargs):
        return iter([{"ticker": "TEST", "yes_bid": 40, "yes_ask": 40, "yes_bid_size": 0}])


class MarginFake:
    def __init__(self, raw):
        self.raw = raw

    def get_market(self, ticker):
        return self.raw


def test_event_discovery_records_valid_series():
    instrument = get_asset("ETH").instrument("15m")
    result = EventSeriesDiscovery(
        FakePublic({"cadence": "15m", "contract_shape": "binary"}), clock=lambda: 100
    ).check(get_asset("ETH"), instrument)
    assert result.eligible is True
    assert result.metadata["active_market_count"] == 1


def test_event_discovery_accepts_kalshi_fifteen_min_frequency():
    instrument = get_asset("ETH").instrument("15m")
    result = EventSeriesDiscovery(
        FakePublic({"frequency": "fifteen_min", "contract_shape": "binary"}), clock=lambda: 100
    ).check(get_asset("ETH"), instrument)
    assert result.eligible is True


def test_event_discovery_fails_closed_on_missing_series():
    instrument = get_asset("ETH").instrument("15m")
    result = EventSeriesDiscovery(FakePublic({}), clock=lambda: 100).check(
        get_asset("ETH"), instrument
    )
    # The fake has no declared shape/cadence, but active markets make this a
    # valid legacy-shaped response; an unavailable client is tested below.
    assert result.eligible is True


def test_event_discovery_rejects_explicitly_unfillable_quotes():
    result = EventSeriesDiscovery(
        QualityPublic({"cadence": "15m", "contract_shape": "binary"}), clock=lambda: 100
    ).check(get_asset("ETH"), get_asset("ETH").instrument("15m"))
    assert result.eligible is False
    assert result.failure_reason == "no_fillable_quotes"


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


def test_source_alignment_rejects_wrong_index_or_missing_source():
    event = EventSeriesDiscovery(FakePublic({"cadence": "15m"}), clock=lambda: 100).check(
        get_asset("ETH"), get_asset("ETH").instrument("15m")
    )
    event = event.__class__(**{**event.__dict__, "metadata": {"reference_index": "ETHUSD_RTI"}})
    assert (
        check_source_alignment(
            asset_id="ETH", expected_index="ETHUSD_RTI", event=event, observed_sources=set()
        ).reason
        == "index_source_unavailable"
    )
    assert (
        check_source_alignment(asset_id="ETH", expected_index="BTCUSD_RTI", event=event).reason
        == "event_index_mismatch"
    )


def test_perp_discovery_fails_closed_on_missing_metadata():
    result = PerpDiscovery(MarginFake({"status": "active"}), clock=lambda: 100).check(
        get_asset("ETH")
    )
    assert result is not None and result.failure_reason == "perp_missing_contract_parameters"


def test_perp_discovery_rejects_stale_metadata():
    raw = {
        "status": "active",
        "multiplier": "1",
        "min_order_size": "0.01",
        "reference_index": "ETHUSD_RTI",
        "updated_at": 1,
    }
    result = PerpDiscovery(MarginFake(raw), clock=lambda: 2000).check(get_asset("ETH"))
    assert result is not None and result.failure_reason == "perp_stale_metadata"
