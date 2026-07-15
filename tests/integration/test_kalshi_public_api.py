"""Live public-API contract checks. Run explicitly: pytest -m integration"""

import pytest

from kalshi_bot.data.kalshi.client import KalshiPublicClient

pytestmark = pytest.mark.integration


def test_series_lookup_no_credentials():
    with KalshiPublicClient(max_reads_per_second=4) as client:
        series = client.get_series("KXBTC")
    assert series["ticker"] == "KXBTC"


def test_settled_markets_and_candles_roundtrip():
    from kalshi_bot.data.kalshi.parse import parse_candle, parse_market

    with KalshiPublicClient(max_reads_per_second=4) as client:
        markets, _ = client.get_markets(series_ticker="KXBTCD", status="settled", limit=5)
        assert markets, "expected settled KXBTCD markets in the retention window"
        row = parse_market(markets[0], series_ticker="KXBTCD")
        candles = client.get_candlesticks(
            "KXBTCD",
            row["ticker"],
            start_ts=row["open_ts"],
            end_ts=row["close_ts"],
            period_minutes=60,
        )
        # settled hourly market must have at least one hourly candle
        assert candles
        parsed = parse_candle(
            candles[0],
            market_ticker=row["ticker"],
            series_ticker="KXBTCD",
            period_minutes=60,
        )
        assert parsed["end_period_ts"] > 0
