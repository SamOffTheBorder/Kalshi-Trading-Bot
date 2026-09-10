from kalshi_bot.data.manifests import idempotency_key


def test_idempotency_key_changes_for_revision_and_parser():
    base = idempotency_key("binance", "BTCUSDT:1", 1000, "r1", "p1")
    assert base == idempotency_key("binance", "BTCUSDT:1", 1000, "r1", "p1")
    assert base != idempotency_key("binance", "BTCUSDT:1", 1000, "r2", "p1")
    assert base != idempotency_key("binance", "BTCUSDT:1", 1000, "r1", "p2")
