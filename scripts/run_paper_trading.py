"""Paper trading loop for KXBTC15M (paper-trading-and-notify tasks.md §4.1/§4.2).

Every cycle:

  1. Poll live KXBTC15M markets from the unauthenticated `/markets` endpoint
     (top-of-book `yes_bid`/`yes_ask` come back on the plain market listing —
     no WebSocket or orderbook subscription needed for a top-of-book paper
     loop; see design note below).
  2. Poll the live BRTI index (Kalshi's authenticated CF Benchmarks
     passthrough, same source `start_capture.bat` uses) and accumulate
     readings in memory for the strategy's settlement-window features.
  3. Build a `StrategyContext` per open market and evaluate
     `SettlementProbStrategy`.
  4. Every Decision — HOLD or not — is persisted via `record_signal`
     (mode="paper"), matching the audit-trail contract the backtest engine
     already honors.
  5. A BUY decision is sized by `size_validation_position` (fixed-risk, not
     Kelly — same sizing the validation backtest uses) and routed through
     `PaperBroker.place_order`. No real order is ever sent to Kalshi.
  6. Markets that have closed are polled for their settlement result, paper
     positions are settled via `PaperBroker.settle_market`, and the realized
     PnL feeds `EmergencyControl` (drawdown + daily-loss + consecutive-loss).
  7. `EmergencyControl.allows_new_entries()` gates every new entry; any of
     its three guards tripping also trips the dashboard's `ControlPanel`
     kill switch, so an operator watching the dashboard sees the same halt
     state this loop is enforcing. Ctrl+C (SIGINT) stops the loop cleanly.

Design note on skipping the WebSocket client (tasks.md §1.1): the plan called
for `orderbook_delta` subscription, but Kalshi's plain `GET /markets` listing
already returns live top-of-book (`yes_bid_dollars`/`yes_ask_dollars`,
refreshed continuously, unauthenticated) for every open market in one call.
A short-poll REST loop gets a paper strategy that only needs top-of-book (not
full depth) live quotes with far less to build and no session/reconnect
state machine. If a future strategy needs book depth this can grow a WS
path without changing the broker/strategy seam.

Foreground only, like `capture_session.py` and `start_capture.bat`: no
scheduler, no service, no unattended process. Ctrl+C stops it cleanly.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from loguru import logger  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from kalshi_bot.config.settings import Settings, get_settings  # noqa: E402
from kalshi_bot.data.brti.kalshi_source import KalshiBRTISource  # noqa: E402
from kalshi_bot.data.brti.poll import BRTIReadingRaw  # noqa: E402
from kalshi_bot.data.kalshi.client import KalshiPublicClient  # noqa: E402
from kalshi_bot.execution.broker_protocol import MarketSnapshot, OrderRequest  # noqa: E402
from kalshi_bot.execution.paper_broker import PaperBroker  # noqa: E402
from kalshi_bot.execution.paper_guard import PaperExecutionGuard  # noqa: E402
from kalshi_bot.risk.daily_loss_guard import ConsecutiveLossGuard, DailyLossGuard  # noqa: E402
from kalshi_bot.risk.drawdown_guard import DrawdownGuard  # noqa: E402
from kalshi_bot.risk.emergency_control import EmergencyControl  # noqa: E402
from kalshi_bot.risk.entry_throttle import EntryThrottle  # noqa: E402
from kalshi_bot.risk.fixed_risk import FixedRiskConfig, size_validation_position  # noqa: E402
from kalshi_bot.signals.settlement_window import BRTIReading  # noqa: E402
from kalshi_bot.storage.db import create_all_tables, get_engine, get_session_factory  # noqa: E402
from kalshi_bot.storage.records import record_signal  # noqa: E402
from kalshi_bot.strategy.base import Action, StrategyContext  # noqa: E402
from kalshi_bot.strategy.settlement_prob import SettlementProbStrategy  # noqa: E402
from kalshi_bot.web.control_state import get_control_panel  # noqa: E402

KXBTC15M_SERIES = "KXBTC15M"

# Bounded so memory doesn't grow unbounded over a long-running loop; a
# window this size comfortably covers several 15-minute contract lifetimes
# plus the 60s settlement averaging windows the strategy needs.
BRTI_HISTORY_MAX = 4_000

DEFAULT_MARKET_POLL_S = 5.0
DEFAULT_BRTI_POLL_S = 5.0


def _build_brti_source(settings: Settings) -> KalshiBRTISource:
    if settings.kalshi_key_id is None:
        raise SystemExit(
            "KALSHI_KEY_ID is not set. The live BRTI feed needs Kalshi's authenticated "
            "CF Benchmarks passthrough (same credentials start_capture.bat uses)."
        )
    return KalshiBRTISource(
        key_id=settings.kalshi_key_id.get_secret_value(),
        private_key_path=settings.kalshi_private_key_path,
    )


def _fetch_open_markets(client: KalshiPublicClient) -> list[dict]:
    markets, _ = client.get_markets(series_ticker=KXBTC15M_SERIES, status="open", limit=50)
    return markets


def _fetch_recent_settled(client: KalshiPublicClient, tickers: set[str]) -> dict[str, str]:
    """result per ticker for the given (presumed just-closed) tickers, by
    asking Kalshi for each market directly rather than re-listing."""
    results: dict[str, str] = {}
    if not tickers:
        return results
    markets, _ = client.get_markets(series_ticker=KXBTC15M_SERIES, status="settled", limit=100)
    by_ticker = {m["ticker"]: m for m in markets}
    for ticker in tickers:
        m = by_ticker.get(ticker)
        if m and m.get("result"):
            results[ticker] = m["result"]
    return results


def _yes_cents(dollars_str: str | None) -> int | None:
    if not dollars_str:
        return None
    try:
        cents = round(float(dollars_str) * 100)
    except ValueError:
        return None
    return cents if 1 <= cents <= 99 else None


def run(
    *,
    settings: Settings,
    session: Session,
    duration_s: float | None,
    market_poll_s: float = DEFAULT_MARKET_POLL_S,
    brti_poll_s: float = DEFAULT_BRTI_POLL_S,
    now_fn=time.time,
    sleep_fn=time.sleep,
) -> None:
    panel = get_control_panel()
    panel.arm()  # this loop running IS the operator's intent to trade paper
    control = EmergencyControl(
        drawdown_guard=DrawdownGuard(
            pause_pct=settings.max_drawdown_pause_pct,
            halt_pct=settings.max_drawdown_halt_pct,
            initial_equity=settings.bankroll_total_usd,
            peak_window_s=int(settings.drawdown_peak_window_days * 86_400),
        ),
        daily_loss_guard=DailyLossGuard(max_daily_loss_usd=settings.max_daily_loss_usd),
        consecutive_loss_guard=ConsecutiveLossGuard(
            max_consecutive_losses=settings.max_consecutive_losses
        ),
        control_panel=panel,
    )
    strategy = SettlementProbStrategy()
    broker = PaperBroker(session, starting_cash_usd=settings.bankroll_total_usd)
    throttle = EntryThrottle(
        max_entries=settings.max_entries_per_series_window,
        window_s=int(settings.entry_throttle_window_hours * 3600),
    )
    risk_config = FixedRiskConfig(
        risk_pct=settings.risk_pct, max_position_pct=settings.max_position_pct
    )

    public_client = KalshiPublicClient()
    brti_source = _build_brti_source(settings)
    brti_history: list[BRTIReading] = []

    start = now_fn()
    last_market_poll = 0.0
    last_brti_poll = 0.0
    seen_tickers: set[str] = set(broker.open_position_tickers())

    logger.info(
        "Paper trading loop starting: bankroll=${:.2f} risk_pct={:.1%} "
        "max_position_pct={:.1%} drawdown pause/halt={:.0%}/{:.0%}",
        settings.bankroll_total_usd,
        settings.risk_pct,
        settings.max_position_pct,
        settings.max_drawdown_pause_pct,
        settings.max_drawdown_halt_pct,
    )

    try:
        while True:
            now = now_fn()
            if duration_s is not None and now - start >= duration_s:
                logger.info("Paper trading loop: duration elapsed, stopping.")
                break

            # -- BRTI poll --------------------------------------------------
            if now - last_brti_poll >= brti_poll_s:
                last_brti_poll = now
                try:
                    raw = brti_source.fetch()
                except Exception as exc:
                    logger.warning("BRTI fetch error: {}", exc)
                    raw = None
                if raw is not None:
                    _record_brti(brti_history, raw)

            # -- market poll + strategy evaluation --------------------------
            if now - last_market_poll >= market_poll_s:
                last_market_poll = now
                _cycle(
                    now_ts=int(now),
                    public_client=public_client,
                    session=session,
                    strategy=strategy,
                    broker=broker,
                    throttle=throttle,
                    control=control,
                    risk_config=risk_config,
                    brti_history=brti_history,
                    seen_tickers=seen_tickers,
                )
                session.commit()

            sleep_fn(0.5)
    except KeyboardInterrupt:
        logger.info("Paper trading loop: interrupted, shutting down cleanly.")
    finally:
        session.commit()
        public_client.close()
        brti_source.close()


def _record_brti(history: list[BRTIReading], raw: BRTIReadingRaw) -> None:
    available_at = raw.available_at if raw.available_at is not None else raw.observed_at
    history.append(
        BRTIReading(observed_at=raw.observed_at, value=raw.value, available_at=available_at)
    )
    if len(history) > BRTI_HISTORY_MAX:
        del history[: len(history) - BRTI_HISTORY_MAX]


def _cycle(
    *,
    now_ts: int,
    public_client: KalshiPublicClient,
    session: Session,
    strategy: SettlementProbStrategy,
    broker: PaperBroker,
    throttle: EntryThrottle,
    control: EmergencyControl,
    risk_config: FixedRiskConfig,
    brti_history: list[BRTIReading],
    seen_tickers: set[str],
) -> None:
    try:
        markets = _fetch_open_markets(public_client)
    except Exception as exc:
        logger.warning("Market poll error: {}", exc)
        return

    now_dt = datetime.fromtimestamp(now_ts, tz=UTC)
    open_tickers = {m["ticker"] for m in markets}

    # Settle anything the loop previously held that's no longer listed active.
    closed_positions = set(broker.open_position_tickers()) - open_tickers
    if closed_positions:
        results = _fetch_recent_settled(public_client, closed_positions)
        for ticker, result in results.items():
            net_pnl = broker.settle_market(ticker, result, now_ts)
            logger.info(
                "Settled paper position {}: result={} net_pnl=${:.2f}",
                ticker,
                result,
                net_pnl or 0.0,
            )
            if net_pnl is not None:
                control.record_trade_pnl(net_pnl, now_dt)

    balance = _run_sync(broker.get_account_balance())
    open_positions = _run_sync(broker.get_open_positions())
    equity = balance + sum(p.avg_entry_price_cents / 100 * p.quantity for p in open_positions)
    control.update_equity(equity, now_ts)

    entries_allowed = control.allows_new_entries(now_dt)
    halted = not entries_allowed

    for m in markets:
        ticker = m["ticker"]
        series_ticker = m.get("series_ticker", KXBTC15M_SERIES)
        seen_tickers.add(ticker)

        snapshot = MarketSnapshot(
            market_ticker=ticker,
            ts=now_ts,
            yes_bid_cents=_yes_cents(m.get("yes_bid_dollars")),
            yes_ask_cents=_yes_cents(m.get("yes_ask_dollars")),
        )
        broker.set_current_quote(snapshot)

        close_ts = _iso_to_ts(m.get("close_time"))
        if close_ts is None:
            continue

        window_open_ts = close_ts - 15 * 60
        usable_brti = tuple(r for r in brti_history if r.usable_at <= now_ts)

        context = StrategyContext(
            market_ticker=ticker,
            series_ticker=series_ticker,
            strike_type=m.get("strike_type") or "greater",
            floor_strike=m.get("floor_strike"),
            cap_strike=m.get("cap_strike"),
            now_ts=now_ts,
            close_ts=close_ts,
            yes_bid_cents=snapshot.yes_bid_cents,
            yes_ask_cents=snapshot.yes_ask_cents,
            spot=0.0,
            vol_annual=0.0,
            vol_source="unavailable",
            brti_readings=usable_brti,
            extras={"window_open_ts": float(window_open_ts)},
        )

        decision = strategy.evaluate(context)
        record_signal(session, decision, context, mode="paper")

        if decision.action == Action.HOLD:
            continue
        if not entries_allowed:
            logger.info(
                "Signal {} {} suppressed: entries not allowed (halted={} reason={})",
                decision.action,
                ticker,
                halted,
                control.snapshot().reason,
            )
            continue
        if ticker in broker.open_position_tickers():
            continue
        if not throttle.allows(series_ticker, now_ts):
            logger.info("Signal {} {} suppressed: entry throttle", decision.action, ticker)
            continue
        if decision.entry_price_cents is None:
            continue

        side = "yes" if decision.action == Action.BUY_YES else "no"
        # A conservative stop for sizing purposes only (paper loop has no
        # fixed-R exit yet): worst case is losing the full contract price.
        stop_price_cents = 0
        quantity = size_validation_position(
            equity_usd=equity,
            entry_price_cents=decision.entry_price_cents,
            stop_price_cents=stop_price_cents,
            config=risk_config,
        )
        if quantity < 1:
            logger.info("Signal {} {} sized to 0 contracts, skipping", decision.action, ticker)
            continue

        # Always a limit order at the price the strategy's edge was computed
        # against (operator decision: never a quick/market buy). PaperBroker
        # rejects any order without a limit, so this is the price the fill
        # can be AT OR BETTER than -- never worse, and never chased.
        order = OrderRequest(
            market_ticker=ticker,
            side=side,
            quantity=int(quantity),
            limit_price_cents=decision.entry_price_cents,
        )
        result = _run_sync(broker.place_order(order))
        if result.status == "filled":
            throttle.record_entry(series_ticker, now_ts)
            logger.info(
                "PAPER FILL: {} {} x{} @ {}c (edge={:.3f})",
                decision.action,
                ticker,
                result.quantity,
                result.fill_price_cents,
                decision.fee_adjusted_edge or 0.0,
            )
        else:
            logger.info("Order rejected for {}: {}", ticker, result.reject_reason)


def _iso_to_ts(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _run_sync(coro):
    """PaperBroker's methods are async (BrokerAdapter protocol parity with a
    real live broker), but this loop is plain synchronous polling — no
    concurrent I/O to gain from asyncio here. Run the coroutine to
    completion without spinning up an event loop per call."""
    import asyncio

    return asyncio.run(coro)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="stop after this many seconds (default: run until Ctrl+C)",
    )
    parser.add_argument("--market-poll-interval", type=float, default=DEFAULT_MARKET_POLL_S)
    parser.add_argument("--brti-poll-interval", type=float, default=DEFAULT_BRTI_POLL_S)
    args = parser.parse_args()

    logger.warning(
        "scripts/run_paper_trading.py is the legacy KXBTC15M-only loop. The "
        "registry-driven replacement is scripts/run_paper.py "
        "(--domain prediction --assets BTC[,ETH,...]); this shim stays for one "
        "release. See multi-venue-paper-trading §8.5."
    )

    settings = get_settings()
    if args.db is not None:
        settings = settings.model_copy(update={"db_path": args.db})

    if not settings.paper_trading:
        raise SystemExit(
            "PAPER_TRADING is set to false in settings/.env. This script only runs paper "
            "mode; flip PAPER_TRADING back to true (or unset it) before running it."
        )

    # The BTC loop uses authenticated BRTI reads.  Do this before building
    # clients so a production-authenticated configuration cannot reach a run.
    PaperExecutionGuard.validate(settings, mode="paper", require_authenticated=True)

    engine = get_engine(settings)
    create_all_tables(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        run(
            settings=settings,
            session=session,
            duration_s=args.duration,
            market_poll_s=args.market_poll_interval,
            brti_poll_s=args.brti_poll_interval,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
