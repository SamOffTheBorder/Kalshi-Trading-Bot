"""Event-driven backtest engine.

Steps hourly through archived history, at each step:
  1. settle markets that closed (official result, fee inside the fill model)
  2. update the drawdown guard with current equity
  3. build a StrategyContext per open market — the SAME context type, the
     SAME strategy.evaluate(), and the SAME Kelly sizing the live loop will
     use. No duplicated decision logic, ever (design decision 1).

Look-ahead discipline: at timestep ts the strategy sees the candle of the
hour ending at ts, the spot close of that same hour, and volatility computed
from daily closes strictly BEFORE ts. The train/test split is engine-enforced
(design decision 6): metrics are segmented by entry time and the go/no-go
reads only the test segment.

Equity is marked at entry cost for open positions (conservative; positions
are held to settlement in this phase).
"""

from __future__ import annotations

import bisect
import math
from collections import defaultdict
from dataclasses import dataclass

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.backtest.liveness import is_live_quote
from kalshi_bot.backtest.metrics import SegmentMetrics, compute_segment_metrics
from kalshi_bot.execution.backtest_broker import BacktestBroker, MarketBar, Settlement
from kalshi_bot.execution.broker_protocol import OrderRequest
from kalshi_bot.risk.drawdown_guard import DrawdownGuard
from kalshi_bot.risk.entry_throttle import EntryThrottle
from kalshi_bot.risk.kelly import size_binary_position
from kalshi_bot.signals.volatility import estimate_volatility
from kalshi_bot.storage.models import BacktestRun, Candle, KalshiMarket, SimulatedTrade, SpotCandle
from kalshi_bot.storage.records import record_signal
from kalshi_bot.strategy.base import Action, StrategyContext, StrategyProtocol
from kalshi_bot.strategy.levels import SpotBar

SERIES_SYMBOL = {
    "KXBTC": "BTC-USD",
    "KXBTCD": "BTC-USD",
    "KXBTC15M": "BTC-USD",  # design D1's primary instrument — found missing here 2026-09-06
    "KXETH": "ETH-USD",
    "KXETHD": "ETH-USD",
}


@dataclass(frozen=True)
class BacktestResult:
    run_id: int
    train: SegmentMetrics
    test: SegmentMetrics
    final_equity: float

    def summary(self) -> str:
        return "\n".join(
            [
                f"BacktestRun #{self.run_id} — final equity ${self.final_equity:.2f}",
                self.train.summary(),
                self.test.summary(),
            ]
        )


class BacktestEngine:
    def __init__(
        self,
        *,
        strategy: StrategyProtocol,
        broker: BacktestBroker,
        session: Session,
        starting_cash_usd: float,
        kelly_fraction: float,
        max_position_pct: float,
        guard: DrawdownGuard,
        throttle: EntryThrottle | None = None,
        candle_period_minutes: int = 1,
        eval_stride_s: int = 300,
        trend_lookback_s: int = 86_400,
        spot_bar_window: int = 48,
        signal_flush_interval: int = 5_000,
    ) -> None:
        """`candle_period_minutes` must be finer than the market lifetime:
        hourly markets get exactly one 60-minute candle — timestamped at the
        market's close, when it's too late to trade — so hourly series are
        only backtestable at 1-minute granularity. `eval_stride_s` throttles
        how often the same market is re-evaluated (matches the ~minutes-scale
        polling cadence a live loop would use, and keeps MC cost sane).
        `spot_bar_window` is how many hourly spot bars (tasks.md 6.1/6.2's
        `StrategyContext.spot_bars`) precede each evaluation — 48 hours by
        default, generous enough for `levels.py`'s default lookback/min-touch
        settings without loading the entire history on every evaluation.
        `signal_flush_interval` bounds how many pending `SignalRecord` INSERTs
        accumulate before a `session.flush()` (tasks.md 8.1 finding: a
        multi-day run at a fine `eval_stride_s` can produce millions of HOLD
        records, and never flushing until the final commit makes every
        subsequent autoflush check progressively slower over the run)."""
        self.strategy = strategy
        self.broker = broker
        self.session = session
        self.starting_cash = starting_cash_usd
        self.kelly_fraction = kelly_fraction
        self.max_position_pct = max_position_pct
        self.guard = guard
        self.throttle = throttle
        self.candle_period_minutes = candle_period_minutes
        self.eval_stride_s = eval_stride_s
        self.trend_lookback_s = trend_lookback_s
        self.spot_bar_window = spot_bar_window
        self._signal_flush_interval = signal_flush_interval

    # -- data loading ------------------------------------------------------------

    def _load_spot(self, symbol: str, period_minutes: int) -> tuple[list[int], list[float]]:
        rows = self.session.execute(
            select(SpotCandle.open_ts, SpotCandle.close)
            .where(SpotCandle.symbol == symbol, SpotCandle.period_minutes == period_minutes)
            .order_by(SpotCandle.open_ts)
        ).all()
        # exchanges may both be present; last write wins per timestamp
        by_ts: dict[int, float] = {}
        for ts, close in rows:
            by_ts[ts] = close
        sorted_ts = sorted(by_ts)
        return sorted_ts, [by_ts[t] for t in sorted_ts]

    @staticmethod
    def _latest_before(ts_list: list[int], values: list[float], ts: int) -> float | None:
        """Value of the latest entry at-or-before ts, None if none exists."""
        idx = bisect.bisect_right(ts_list, ts) - 1
        return values[idx] if idx >= 0 else None

    def _load_spot_bars(self, symbol: str, period_minutes: int) -> list[SpotBar]:
        """Full-OHLCV spot history for `strategy.levels`-based strategies
        (tasks.md 6.1/6.2), sorted by `open_ts`. Kept separate from
        `_load_spot` (close-only, used by the vol/trend-zscore path) rather
        than changing that method's return shape — `_load_spot` has an
        established call site and contract, and most callers don't need
        high/low/volume at all."""
        rows = self.session.execute(
            select(SpotCandle)
            .where(SpotCandle.symbol == symbol, SpotCandle.period_minutes == period_minutes)
            .order_by(SpotCandle.open_ts)
        ).scalars()
        # exchanges may both be present; last write wins per timestamp
        by_ts: dict[int, SpotBar] = {}
        for row in rows:
            by_ts[row.open_ts] = SpotBar(
                ts=row.open_ts,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
            )
        return [by_ts[t] for t in sorted(by_ts)]

    @staticmethod
    def _bars_before(
        bars: list[SpotBar], bar_ts: list[int], ts: int, *, max_bars: int
    ) -> tuple[SpotBar, ...]:
        """The most recent `max_bars` bars strictly before `ts`, oldest
        first — same look-ahead discipline as the rest of context assembly
        (spot/vol are computed from data strictly before `ts`). `bar_ts` is
        `[b.ts for b in bars]`, precomputed once by the caller rather than
        rebuilt on every evaluation."""
        idx = bisect.bisect_left(bar_ts, ts)
        return tuple(bars[max(0, idx - max_bars) : idx])

    # -- main loop ------------------------------------------------------------------

    async def run(self, *, start_ts: int, end_ts: int, split_ts: int) -> BacktestResult:
        if not start_ts < split_ts < end_ts:
            raise ValueError("require start_ts < split_ts < end_ts (enforced split)")

        run_row = BacktestRun(
            strategy_name=self.strategy.name,
            params={
                "kelly_fraction": self.kelly_fraction,
                "max_position_pct": self.max_position_pct,
                "starting_cash_usd": self.starting_cash,
            },
            data_start_ts=start_ts,
            data_end_ts=end_ts,
            split_ts=split_ts,
        )
        self.session.add(run_row)
        self.session.flush()

        markets = {
            m.ticker: m
            for m in self.session.execute(
                select(KalshiMarket).where(
                    KalshiMarket.close_ts > start_ts,
                    KalshiMarket.close_ts <= end_ts,
                    KalshiMarket.result.is_not(None),
                    KalshiMarket.result != "",
                )
            ).scalars()
        }
        candles_by_ts: dict[int, list[Candle]] = defaultdict(list)
        for candle in self.session.execute(
            select(Candle).where(
                Candle.end_period_ts >= start_ts,
                Candle.end_period_ts <= end_ts,
                Candle.period_minutes == self.candle_period_minutes,
            )
        ).scalars():
            if candle.market_ticker in markets:
                candles_by_ts[candle.end_period_ts].append(candle)

        markets_by_close: dict[int, list[KalshiMarket]] = defaultdict(list)
        for m in markets.values():
            markets_by_close[m.close_ts].append(m)

        spot_hourly: dict[str, tuple[list[int], list[float]]] = {}
        spot_daily: dict[str, tuple[list[int], list[float]]] = {}
        spot_bars_hourly: dict[str, list[SpotBar]] = {}
        spot_bars_ts: dict[str, list[int]] = {}
        for symbol in set(SERIES_SYMBOL.values()):
            spot_hourly[symbol] = self._load_spot(symbol, 60)
            spot_daily[symbol] = self._load_spot(symbol, 1440)
            spot_bars_hourly[symbol] = self._load_spot_bars(symbol, 60)
            spot_bars_ts[symbol] = [b.ts for b in spot_bars_hourly[symbol]]

        timeline = sorted(set(candles_by_ts) | set(markets_by_close))
        equity_curve: list[tuple[int, float]] = []
        entry_ts_by_market: dict[str, int] = {}
        last_eval_ts: dict[str, int] = {}
        trade_rows: dict[str, SimulatedTrade] = {}
        # Fixed-R exit levels (contract-cents) for markets whose entry decision
        # declared them (tasks.md 6.1/6.2 + 8.1's engine extension). A market
        # not in this dict rides to settlement exactly as before — this is
        # purely additive, opt-in per decision.
        exit_levels_by_market: dict[str, tuple[int, int, str]] = {}  # (stop, target, side)
        evaluated = 0
        entered = 0
        fills_rejected_outside_band = 0
        dead_quotes = 0
        closed_early = 0

        for ts in timeline:
            # 1. fixed-R exit check: for every open position with declared
            # stop/target cents, check THIS market's own candle at ts for a
            # crossing before settlement is considered — see
            # `strategy.base.Decision.stop_price_cents`'s docstring for why
            # this is checked in contract-cents against the market's own
            # candle rather than derived from spot.
            for candle in candles_by_ts.get(ts, []):
                levels = exit_levels_by_market.get(candle.market_ticker)
                if levels is None:
                    continue
                stop_cents, target_cents, side = levels
                exit_price = _fixed_r_exit_price(candle, side, stop_cents, target_cents)
                if exit_price is None:
                    continue
                settlement = self.broker.close_position_early(candle.market_ticker, exit_price, ts)
                if settlement is None:
                    continue
                del exit_levels_by_market[candle.market_ticker]
                closed_early += 1
                trade = trade_rows.get(candle.market_ticker)
                if trade is not None:
                    trade.exit_ts = ts
                    trade.exit_price_cents = exit_price
                    trade.status = "closed_early"
                    trade.gross_pnl_usd = settlement.gross_pnl_usd
                    trade.fee_usd = settlement.fee_usd
                    trade.net_pnl_usd = settlement.net_pnl_usd

            # 2. settle everything that closed at/by this timestep (a
            # position already closed early above is no longer open, so
            # settle_market's own no-op-if-absent guard makes this safe)
            for market in markets_by_close.get(ts, []):
                exit_levels_by_market.pop(market.ticker, None)
                self.broker.settle_market(market.ticker, market.result or "", ts)
                trade = trade_rows.get(market.ticker)
                if trade is not None and self.broker.settlements:
                    s = self.broker.settlements[-1]
                    if s.market_ticker == market.ticker and trade.status == "open":
                        trade.exit_ts = ts
                        trade.exit_price_cents = 100 if s.won else 0
                        trade.status = "settled_won" if s.won else "settled_lost"
                        trade.gross_pnl_usd = s.gross_pnl_usd
                        trade.fee_usd = s.fee_usd
                        trade.net_pnl_usd = s.net_pnl_usd

            # 3. equity + guard (open positions marked at entry cost)
            cash = await self.broker.get_account_balance()
            open_positions = await self.broker.get_open_positions()
            equity = cash + sum(p.quantity * p.avg_entry_price_cents / 100 for p in open_positions)
            equity_curve.append((ts, equity))
            self.guard.update(equity, ts=ts)

            # 3. evaluate open markets with a candle this hour
            for candle in candles_by_ts.get(ts, []):
                market = markets[candle.market_ticker]
                if market.close_ts <= ts or market.ticker in entry_ts_by_market:
                    continue
                last = last_eval_ts.get(market.ticker)
                if last is not None and ts - last < self.eval_stride_s:
                    continue
                last_eval_ts[market.ticker] = ts
                symbol = SERIES_SYMBOL.get(market.series_ticker)
                if symbol is None:
                    continue
                hourly_ts, hourly_close = spot_hourly[symbol]
                spot = self._latest_before(hourly_ts, hourly_close, ts)
                if spot is None:
                    continue
                daily_ts, daily_close = spot_daily[symbol]
                cutoff = bisect.bisect_left(daily_ts, ts)
                daily_history = daily_close[:cutoff]
                try:
                    vol = estimate_volatility(daily_history)
                except ValueError:
                    continue

                # trend z-score: realized log-return over the lookback window,
                # normalized by the zero-drift model's expected scale (sigma*sqrt(t))
                trend_z: float | None = None
                spot_then = self._latest_before(hourly_ts, hourly_close, ts - self.trend_lookback_s)
                if spot_then is not None and spot_then > 0 and vol.vol_annual > 0:
                    lookback_years = self.trend_lookback_s / (365 * 24 * 3600)
                    trend_z = math.log(spot / spot_then) / (
                        vol.vol_annual * math.sqrt(lookback_years)
                    )

                spot_bars = self._bars_before(
                    spot_bars_hourly[symbol],
                    spot_bars_ts[symbol],
                    ts,
                    max_bars=self.spot_bar_window,
                )

                context = StrategyContext(
                    market_ticker=market.ticker,
                    series_ticker=market.series_ticker,
                    strike_type=market.strike_type or "greater",
                    floor_strike=market.floor_strike,
                    cap_strike=market.cap_strike,
                    now_ts=ts,
                    close_ts=market.close_ts,
                    yes_bid_cents=candle.yes_bid_close,
                    yes_ask_cents=candle.yes_ask_close,
                    spot=spot,
                    vol_annual=vol.vol_annual,
                    vol_source=vol.source,
                    trend_zscore=trend_z,
                    spot_bars=spot_bars,
                )
                decision = self.strategy.evaluate(context)
                evaluated += 1
                signal_row = record_signal(
                    self.session, decision, context, mode="backtest", backtest_run_id=run_row.id
                )
                if evaluated % self._signal_flush_interval == 0:
                    # A multi-day run at a fine eval_stride_s can produce
                    # millions of HOLD SignalRecord objects; leaving them all
                    # as pending INSERTs until the final commit makes every
                    # subsequent autoflush check progressively slower
                    # (observed: an 8.1 backtest run over 636k evaluations
                    # visibly decelerating over its ~3-minute run).
                    # Flushing periodically bounds how many pending INSERTs
                    # accumulate. Deliberately NOT `expire_all()` here: open
                    # `SimulatedTrade` rows in `trade_rows` are mutated
                    # in-place later (on settlement/early-close, elsewhere
                    # in this loop) without re-fetching from the session —
                    # expiring them would risk a stale read on next access.
                    self.session.flush()

                if decision.action == Action.HOLD:
                    continue
                if not self.guard.allows_new_entries():
                    continue
                if self.throttle is not None and not self.throttle.allows(market.series_ticker, ts):
                    continue
                if not is_live_quote(candle):
                    # Mandatory liveness filter (spec: "Only live markets are
                    # tradeable"). 92/100 sampled KXBTCD strikes were 0c/1c
                    # shells with zero OI — Phase 1's backtest filled against
                    # these phantom quotes. The strategy still gets evaluated
                    # and its decision recorded above (audit trail), but no
                    # entry is ever generated for a dead market.
                    dead_quotes += 1
                    continue

                p_win = (
                    decision.bs_probability
                    if decision.action == Action.BUY_YES
                    else 1.0 - (decision.bs_probability or 0.0)
                )
                if p_win is None or decision.entry_price_cents is None:
                    continue
                # Re-mark bankroll immediately before sizing THIS position,
                # not once per timestep, and size against AVAILABLE CASH, not
                # total equity (tasks.md 8.3 finding, 2026-09-06, two related
                # bugs found in sequence):
                #
                # 1. When many correlated strikes fire in the same evaluation
                #    batch (e.g. every threshold on one BTC move), each
                #    entry's `create_order` call already debits the broker's
                #    real cash synchronously — but Kelly sizing was reading
                #    the STALE pre-batch `equity` for every position in the
                #    batch, so each one sized against the full starting
                #    bankroll as if it were the only position opened that
                #    step. Diagnosed via a real run: ~24 simultaneous entries
                #    each Kelly-sized off the same bankroll figure produced
                #    an aggregate exposure far beyond any single position's
                #    own cap, manifesting as a transient equity-marking
                #    "HALT" that had nothing to do with real risk (every one
                #    of those positions settled favorably 60 seconds later).
                # 2. Fixing #1 by re-marking EQUITY (cash + value of already-
                #    open positions) per entry wasn't enough: equity doesn't
                #    shrink when cash converts into a new position (the
                #    position's own cost is still counted as "yours"), so
                #    concurrent correlated entries within one batch still
                #    each saw ~the full original bankroll and sized as if it
                #    were still free to spend — `place_order`'s own
                #    `cost > self._cash` check then rejected most of them
                #    outright (all-or-nothing) rather than letting them size
                #    down proportionally. Sizing against AVAILABLE CASH only
                #    (excluding money already locked in other open
                #    positions) is the correct proxy: it's conservative,
                #    matches what a real margin check would allow you to
                #    spend, and lets a second/third correlated entry in the
                #    same batch size down instead of being flatly rejected.
                live_cash = await self.broker.get_account_balance()
                quantity = size_binary_position(
                    p_win=p_win,
                    cost_cents=decision.entry_price_cents,
                    bankroll_usd=live_cash,
                    kelly_fraction=self.kelly_fraction,
                    max_position_pct=self.max_position_pct,
                )
                if quantity <= 0:
                    continue

                self.broker.set_current_bar(
                    MarketBar(
                        market_ticker=market.ticker,
                        ts=ts,
                        yes_bid_low=candle.yes_bid_low,
                        yes_bid_close=candle.yes_bid_close,
                        yes_ask_high=candle.yes_ask_high,
                        yes_ask_close=candle.yes_ask_close,
                        volume=candle.volume,
                        yes_bid_high=candle.yes_bid_high,
                        yes_ask_low=candle.yes_ask_low,
                    )
                )
                side = "yes" if decision.action == Action.BUY_YES else "no"
                result = await self.broker.place_order(
                    OrderRequest(market_ticker=market.ticker, side=side, quantity=quantity)
                )
                if result.status != "filled":
                    continue

                # Entry gates are evaluated against the ACTUAL FILL, not the
                # price the strategy gated on at decision time (spec:
                # backtest-engine "Entry gates are evaluated against the
                # actual fill"). Pessimistic fills can land worse than the
                # decision price; a fill outside the strategy's own declared
                # band is voided rather than recorded as a position — this is
                # the fix for Phase 1's 18/64 (28%) out-of-band trades.
                fill_price = result.fill_price_cents
                if fill_price is not None and (
                    (
                        decision.min_entry_price_cents is not None
                        and fill_price < decision.min_entry_price_cents
                    )
                    or (
                        decision.max_entry_price_cents is not None
                        and fill_price > decision.max_entry_price_cents
                    )
                ):
                    self.broker.void_fill(market.ticker)
                    fills_rejected_outside_band += 1
                    logger.warning(
                        "{}: fill at {}c rejected, outside entry band [{}, {}]",
                        market.ticker,
                        fill_price,
                        decision.min_entry_price_cents,
                        decision.max_entry_price_cents,
                    )
                    continue

                entered += 1
                if self.throttle is not None:
                    self.throttle.record_entry(market.series_ticker, ts)
                entry_ts_by_market[market.ticker] = ts
                if (
                    decision.stop_price_cents is not None
                    and decision.target_price_cents is not None
                ):
                    exit_levels_by_market[market.ticker] = (
                        decision.stop_price_cents,
                        decision.target_price_cents,
                        side,
                    )
                self.session.flush()
                trade_rows[market.ticker] = SimulatedTrade(
                    backtest_run_id=run_row.id,
                    signal_id=signal_row.id,
                    mode="backtest",
                    market_ticker=market.ticker,
                    side=side,
                    quantity=result.quantity,
                    entry_price_cents=result.fill_price_cents or 0,
                    entry_ts=ts,
                    status="open",
                )
                self.session.add(trade_rows[market.ticker])

        # -- segment metrics by ENTRY time (enforced out-of-sample split) --------
        def segment(
            predicate,
        ) -> tuple[list[Settlement], list[tuple[int, float]]]:
            settlements = [
                s
                for s in self.broker.settlements
                if s.market_ticker in entry_ts_by_market
                and predicate(entry_ts_by_market[s.market_ticker])
            ]
            curve = [(t, e) for t, e in equity_curve if predicate(t)]
            return settlements, curve

        train_settle, train_curve = segment(lambda t: t < split_ts)
        test_settle, test_curve = segment(lambda t: t >= split_ts)
        train = compute_segment_metrics("train", train_settle, train_curve)
        test = compute_segment_metrics("test", test_settle, test_curve)

        final_equity = equity_curve[-1][1] if equity_curve else self.starting_cash
        run_row.status = "completed"
        run_row.metrics_train = train.to_dict()
        run_row.metrics_test = test.to_dict()
        self.session.commit()

        logger.info(
            "backtest run {} complete: {} evaluations, {} entries, {} settlements "
            "({} closed early on stop/target), {} fills rejected (outside entry band), "
            "{} dead-quote markets skipped",
            run_row.id,
            evaluated,
            entered,
            len(self.broker.settlements),
            closed_early,
            fills_rejected_outside_band,
            dead_quotes,
        )
        return BacktestResult(run_id=run_row.id, train=train, test=test, final_equity=final_equity)


def _fixed_r_exit_price(
    candle: Candle, side: str, stop_cents: int, target_cents: int
) -> int | None:
    """Check ONE candle (this market's own 1-minute contract candle, tasks.md
    8.1) for a fixed-R stop/target crossing. Pessimistic about the ORDER of
    events within the bar, same discipline as `BacktestBroker`'s entry fill
    model: if a bar's range touches BOTH the stop and the target, the stop is
    assumed to have been hit FIRST (the worse outcome for the position) —
    this cannot be known from OHLC alone, and assuming the favorable order
    would be exactly the kind of optimistic-fill lie design decision 4
    already rejects for entries.

    A `yes` position's contract price tracks `price_high`/`price_low`
    directly. A `no` position's economic price is `100 - yes_price`, so its
    stop/target (already expressed as NO-price-equivalent cents by the
    strategy) are checked against `100 - price_low`/`100 - price_high`
    (inverted high/low, since a low YES print is a HIGH point for NO).

    Returns the trade-price cents to exit at (the crossed level itself, not
    the bar's extreme) or None if neither level was reached this bar.
    """
    if candle.price_high is None or candle.price_low is None:
        return None
    if side == "yes":
        high, low = candle.price_high, candle.price_low
    else:
        # NO-equivalent price range: a low YES print is NO's high, and vice versa.
        high, low = 100 - candle.price_low, 100 - candle.price_high

    stop_hit = low <= stop_cents
    target_hit = high >= target_cents
    if stop_hit and target_hit:
        return stop_cents  # ambiguous order within the bar -> assume the worse outcome
    if stop_hit:
        return stop_cents
    if target_hit:
        return target_cents
    return None
