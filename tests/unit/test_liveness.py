"""Market liveness filter: reject phantom quotes (spec: backtest-engine
"Only live markets are tradeable"). 92/100 sampled KXBTCD strikes were 0c/1c
shells with zero OI — the concrete failure mode this guards against."""

from kalshi_bot.backtest.liveness import is_live_quote
from kalshi_bot.storage.models import Candle


def make_candle(**overrides) -> Candle:
    defaults = dict(
        market_ticker="KXBTCD-T-1",
        series_ticker="KXBTCD",
        period_minutes=60,
        end_period_ts=1_784_000_000,
        yes_bid_close=44,
        yes_ask_close=46,
        volume=100,
        open_interest=10,
    )
    defaults.update(overrides)
    return Candle(**defaults)


def test_two_sided_nonzero_oi_is_live():
    assert is_live_quote(make_candle()) is True


def test_zero_open_interest_is_dead():
    assert is_live_quote(make_candle(open_interest=0)) is False


def test_missing_bid_is_dead():
    assert is_live_quote(make_candle(yes_bid_close=None)) is False


def test_missing_ask_is_dead():
    assert is_live_quote(make_candle(yes_ask_close=None)) is False


def test_zero_cent_bid_shell_is_dead():
    """The concrete Phase 1 failure mode: a 0c/1c 'quote' with no real market."""
    assert is_live_quote(make_candle(yes_bid_close=0, yes_ask_close=1, open_interest=0)) is False


def test_hundred_cent_quote_is_degenerate_not_live():
    assert is_live_quote(make_candle(yes_bid_close=100, yes_ask_close=100)) is False
