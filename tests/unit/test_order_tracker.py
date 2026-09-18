from __future__ import annotations

from kalshi_bot.execution.order_tracker import OrderTracker
from kalshi_bot.execution.safety import require_linear_hedge_instrument


def test_tracker_survives_restart_and_keeps_partial_remainder(tmp_path):
    path = tmp_path / "orders.json"
    tracker = OrderTracker(path, clock=lambda: 100)
    tracker.register("client-1", market_ticker="KXBTCPERP", requested_quantity=5)
    tracker.record_fill("client-1", 2, price=50000)

    restarted = OrderTracker(path, clock=lambda: 101)
    order = restarted.orders["client-1"]
    assert order.status == "partial"
    assert order.remaining_quantity == 3


def test_reconcile_adopts_fill_that_landed_while_down(tmp_path):
    tracker = OrderTracker(tmp_path / "orders.json", clock=lambda: 100)
    tracker.reconcile([{
        "client_order_id": "client-2", "order_id": "broker-2", "ticker": "KXBTCPERP",
        "count": 4, "filled_count": 4, "status": "executed",
    }])
    assert tracker.orders["client-2"].status == "filled"


def test_stale_cancel_records_only_after_callback(tmp_path):
    tracker = OrderTracker(tmp_path / "orders.json", clock=lambda: 100)
    tracker.register("client-3", market_ticker="KXBTCPERP", requested_quantity=1)
    cancelled = []
    tracker.cancel_stale(cancelled.append, now_ts=110, max_age_seconds=10)
    assert cancelled[0].client_order_id == "client-3"
    assert tracker.orders["client-3"].status == "cancelled"


def test_binary_contract_is_rejected_as_linear_hedge():
    try:
        require_linear_hedge_instrument("KXBTC15M-TEST")
    except ValueError as exc:
        assert "linear hedge" in str(exc)
    else:
        raise AssertionError("binary hedge was accepted")
