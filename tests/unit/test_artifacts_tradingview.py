from io import StringIO

import pytest

from kalshi_bot.data.artifacts import ArtifactPathError, artifact_path
from kalshi_bot.data.tradingview_import import (
    TradingViewImportError,
    TradingViewMetadata,
    parse_tradingview_csv,
)


def test_artifact_path_is_content_addressed_and_safe(tmp_path):
    digest = "a" * 64
    assert artifact_path(tmp_path, digest, "bars.zip").parent.name == "aa"
    with pytest.raises(ArtifactPathError):
        artifact_path(tmp_path, digest, "../escape.zip")


def test_tradingview_import_requires_metadata_and_is_ordered():
    metadata = TradingViewMetadata("BINANCE:BTCUSDT", "60", "UTC", "2026-09-08T00:00:00Z", "USDT")
    bars = parse_tradingview_csv(
        StringIO("time,open,high,low,close,volume\n1,1,2,0,1.5,4\n2,1.5,3,1,2,5\n"), metadata
    )
    assert len(bars) == 2 and bars[0].close == 1.5
    with pytest.raises(TradingViewImportError):
        parse_tradingview_csv(
            StringIO("time,open,high,low,close\n1,1,2,0,1\n"),
            TradingViewMetadata("", "60", "UTC", "x", "USDT"),
        )
