from kalshi_bot.data.market_data import (
    MarketDataAdapter,
    MarketDataCapabilities,
    MarketDataCapability,
    MarketDataResult,
)
from kalshi_bot.domain.prediction import Venue


class PollingOnlyAdapter:
    venue = Venue.KALSHI
    capabilities = MarketDataCapabilities(
        supported=frozenset(
            {
                MarketDataCapability.LIST_SPORTS,
                MarketDataCapability.LIST_LEAGUES,
                MarketDataCapability.LIST_EVENTS,
                MarketDataCapability.LIST_MARKETS,
                MarketDataCapability.MARKET_DETAIL,
                MarketDataCapability.BBO,
                MarketDataCapability.ORDER_BOOK,
                MarketDataCapability.PRICE_HISTORY,
            }
        )
    )

    def list_sports(self):
        return MarketDataResult.success(("baseball",))

    def list_leagues(self, *, sport=None):
        return MarketDataResult.success(("MLB",))

    def list_events(self, *, sport=None, league=None, starts_after=None, starts_before=None):
        return MarketDataResult.success(())

    def list_markets(self, *, event_id=None):
        return MarketDataResult.success(())

    def get_market(self, instrument):
        raise NotImplementedError

    def get_bbo(self, instrument):
        raise NotImplementedError

    def get_order_book(self, instrument):
        raise NotImplementedError

    def get_price_history(self, instrument, *, starts_at=None, ends_at=None):
        return MarketDataResult.success(())

    def stream_quotes(self, instruments):
        return MarketDataResult.not_supported(
            MarketDataCapability.QUOTE_STREAM,
            reason="adapter supports polling only",
        )


def test_polling_adapter_declares_and_reports_unsupported_streaming():
    adapter = PollingOnlyAdapter()

    assert isinstance(adapter, MarketDataAdapter)
    assert adapter.capabilities.supports(MarketDataCapability.BBO)
    assert not adapter.capabilities.supports(MarketDataCapability.QUOTE_STREAM)

    result = adapter.stream_quotes(())
    assert not result.is_supported
    assert result.value is None
    assert result.unsupported is not None
    assert result.unsupported.capability is MarketDataCapability.QUOTE_STREAM
    assert result.unsupported.reason == "adapter supports polling only"


def test_market_data_protocol_exposes_no_execution_or_account_operations():
    forbidden = {
        "place_order",
        "cancel_order",
        "get_account_balance",
        "get_open_positions",
        "connect_wallet",
        "wallet",
        "broker_name",
    }

    assert forbidden.isdisjoint(vars(MarketDataAdapter))
    assert forbidden.isdisjoint(capability.value for capability in MarketDataCapability)


def test_unsupported_result_requires_a_specific_nonempty_reason():
    try:
        MarketDataResult.not_supported(MarketDataCapability.QUOTE_STREAM, reason=" ")
    except ValueError as exc:
        assert str(exc) == "unsupported capability reason must not be empty"
    else:
        raise AssertionError("empty unsupported-capability reasons must be rejected")
