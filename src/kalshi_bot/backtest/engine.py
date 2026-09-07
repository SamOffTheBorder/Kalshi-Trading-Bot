"""Event-driven backtest engine.

Steps through archived history event by event. At each timestep ts:
  1. run intrabar fixed-R stop/target exit checks against this bar
  2. settle markets that closed (official result, fee inside the fill model)
  3. execute DEFERRED entry orders decided at an earlier timestep, against
     THIS timestep's candle (kxbtc15m-validation-rebuild §2.1/§2.2)
  4. update the drawdown guard with current equity
  5. build a StrategyContext per open market — the SAME context type, the
     SAME strategy.evaluate(), and the SAME sizing the live loop will use.
     No duplicated decision logic, ever (design decision 1). A decision that
     would enter is QUEUED, not filled here.

Causal-timeline discipline (kxbtc15m-validation-rebuild, decision "Use an
as-of event timeline"): a decision made from the candle ending at ts may
consume only observations at or before ts, and its order is eligible to
execute only on a LATER market-data event — the next candle for that market,
at ts' > ts. The engine never fills an order inside the same bar whose close
the decision consumed; a bar's high/low/close cannot fill an order placed
"during" that bar. Bar-only history therefore supports only bar-close
decisions with next-bar-or-later execution. A queued entry whose market
closes before any next candle arrives simply expires unfilled.

The train/test split is engine-enforced (design decision 6): metrics are
segmented by ENTRY time (the fill timestep) and the go/no-go reads only the
test segment. Equity is marked at entry cost for open positions
(conservative; positions are held to settlement unless a fixed-R exit ends
them sooner).
"""

from __future__ import annotations

import bisect
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from kalshi_bot.backtest.liveness import is_live_quote
from kalshi_bot.backtest.metrics import SegmentMetrics, compute_segment_metrics
from kalshi_bot.execution.backtest_broker import BacktestBroker, MarketBar, Settlement
from kalshi_bot.execution.broker_protocol import OrderRequest
from kalshi_bot.risk.drawdown_guard import DrawdownGuard
from kalshi_bot.risk.entry_throttle import EntryThrottle
from kalshi_bot.risk.fixed_risk import FixedRiskConfig, size_validation_position
from kalshi_bot.risk.kelly import size_binary_position
from kalshi_bot.signals.settlement_window import BRTIReading
from kalshi_bot.signals.volatility import estimate_volatility
from kalshi_bot.storage.models import (
    BacktestRun,
    BRTIObservation,
    Candle,
    KalshiMarket,
    SignalRecord,
    SimulatedTrade,
    SpotCandle,
)
from kalshi_bot.storage.records import record_signal
from kalshi_bot.strategy.base import Action, Decision, StrategyContext, StrategyProtocol
from kalshi_bot.strategy.levels import SpotBar

# How far back from an evaluation the settlement-aware strategies read BRTI:
# the full 15-minute KXBTC15M lifetime, the 60 s reference average at the
# window open, and the short-horizon trend lookback all fit inside 30 min.
_BRTI_SLICE_WINDOW_S = 1_800

# `BRTIObservation.source` labels that mean "the Bitcoin index" — used to
# exclude other CF Benchmarks indices (ETHUSD_RTI, SOLUSD_RTI, ...) captured
# into the same archive. The `%brti%` ilike also matches the historical
# "brti" / "kalshi:cfbenchmarks/BRTI" tags.
_BTC_BRTI_SOURCE_LABELS = ("brti", "BRTI", "kalshi:cfbenchmarks/BRTI")

SERIES_SYMBOL = {
    "KXBTC": "BTC-USD",
    "KXBTCD": "BTC-USD",
    "KXBTC15M": "BTC-USD",  # design D1's primary instrument — found missing here 2026-09-06
    "KXETH": "ETH-USD",
    "KXETHD": "ETH-USD",
}


@dataclass
class PendingEntry:
    """An entry decision made at `decided_ts` from the candle ending then,
    waiting to execute against the NEXT candle for its market (kxbtc15m-
    validation-rebuild §2.1/§2.2). Holds everything the fill step needs so
    it does not re-derive anything from post-decision data — the decision,
    its side, the series, the signal-row id for the trade FK, and the market
    close_ts so a pending order can expire if the market settles before any
    next candle arrives."""

    market_ticker: str
    series_ticker: str
    decided_ts: int
    close_ts: int
    decision: Decision
    side: Literal["yes", "no"]
    signal_row: SignalRecord  # the decision's audit row; .id read after flush at fill time


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
        sizing_mode: Literal["kelly", "fixed_risk"] = "kelly",
        fixed_risk_config: FixedRiskConfig | None = None,
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
        subsequent autoflush check progressively slower over the run).

        `sizing_mode` selects the position-sizing rule at fill time.
        `"kelly"` (default, `risk/kelly.size_binary_position`) is retained for
        diagnostic comparison runs. `"fixed_risk"`
        (`risk/fixed_risk.size_validation_position`) is the validation path
        (kxbtc15m-validation-rebuild §3.1): fixed fraction of equity risked
        against the executable stop distance and both-leg costs, never Kelly.
        A hold-to-settlement binary has no contract stop, so its worst case
        is the full premium — the fixed-risk sizer is called with
        `stop_price_cents=0` and `include_exit_fee=False` in that case.
        `fixed_risk_config` supplies the risk fraction / caps; defaults to
        `FixedRiskConfig()` when `sizing_mode == "fixed_risk"`."""
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
        self.sizing_mode = sizing_mode
        self.fixed_risk_config = fixed_risk_config or (
            FixedRiskConfig() if sizing_mode == "fixed_risk" else None
        )

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

    def _load_brti(self, start_ts: int, end_ts: int) -> tuple[list[int], tuple[BRTIReading, ...]]:
        """`BRTIObservation` rows for the BITCOIN index within the run window,
        oldest first, as `signals.settlement_window.BRTIReading`
        (kxbtc15m-validation-rebuild §4.1). Returned alongside a parallel list
        of `usable_at` timestamps so the per-evaluation slice is a bisect, not
        a scan. `value_dollars` is a decimal string in the schema; parsed to
        float here. A checkout with no BRTI rows yields an empty tuple and the
        settlement strategy HOLDs on `no_brti_readings` — never a crash.

        The archive may hold other CF Benchmarks indices (ETHUSD_RTI etc.)
        captured alongside BRTI; this filters to Bitcoin by `source` so a
        KXBTC15M run never mixes another asset's index into the settlement
        calculation. Historical rows predate the multi-index `source` label
        and used the plain "brti" tag, so both are accepted."""
        rows = self.session.execute(
            select(BRTIObservation)
            .where(
                BRTIObservation.observed_at >= start_ts - 3_600,
                BRTIObservation.observed_at <= end_ts,
                or_(
                    BRTIObservation.source.is_(None),
                    BRTIObservation.source.in_(_BTC_BRTI_SOURCE_LABELS),
                    BRTIObservation.source.ilike("%brti%"),
                ),
            )
            .order_by(BRTIObservation.available_at)
        ).scalars()
        readings = tuple(
            BRTIReading(
                observed_at=r.observed_at,
                value=float(r.value_dollars),
                available_at=r.available_at,
            )
            for r in rows
        )
        return [r.usable_at for r in readings], readings

    @staticmethod
    def _brti_before(
        usable_ts: list[int], readings: tuple[BRTIReading, ...], ts: int, *, window_s: int
    ) -> tuple[BRTIReading, ...]:
        """BRTI readings usable at-or-before `ts` and no older than
        `window_s` before it, oldest first. `window_s` bounds the slice to
        what the settlement-window model actually consumes (its reference and
        current 60 s averages plus a trend lookback) so a multi-day run does
        not hand the strategy the entire index history on every evaluation."""
        hi = bisect.bisect_right(usable_ts, ts)
        lo = bisect.bisect_left(usable_ts, ts - window_s, 0, hi)
        return readings[lo:hi]

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

    # -- deferred entry execution ------------------------------------------------

    async def _execute_pending(
        self,
        pending: PendingEntry,
        candle: Candle,
        fill_ts: int,
        *,
        run_id: int,
        trade_rows: dict[str, SimulatedTrade],
        entry_ts_by_market: dict[str, int],
        exit_levels_by_market: dict[str, tuple[int, int, Literal["yes", "no"]]],
    ) -> str:
        """Execute one previously-queued entry against `candle` (the next
        candle for its market, strictly after the decision's own bar —
        kxbtc15m-validation-rebuild §2.1/§2.2). Every gate and the sizing
        run HERE against fill-time state:

        - guard / throttle checked at `fill_ts`, not decision time
        - liveness checked against the FILL candle
        - bankroll re-marked and sized against available cash immediately
          before the order (tasks.md 8.3: concurrent correlated fills must
          share one capital ledger — still true here, since several pending
          orders can drain against the same timestep)
        - the entry band is checked against the ACTUAL FILL price

        Returns one of: "filled", "rejected_band", "dead_quote",
        "no_fill" (guard/throttle/size/broker rejected it).
        """
        decision = pending.decision
        ticker = pending.market_ticker

        if not self.guard.allows_new_entries():
            return "no_fill"
        if self.throttle is not None and not self.throttle.allows(pending.series_ticker, fill_ts):
            return "no_fill"
        if not is_live_quote(candle):
            # Mandatory liveness filter (spec: "Only live markets are
            # tradeable"), checked against the FILL candle — a market that
            # went dead between decision and fill must not be entered.
            return "dead_quote"

        assert decision.fair_probability is not None  # checked before queuing
        assert decision.entry_price_cents is not None
        live_cash = await self.broker.get_account_balance()
        if self.sizing_mode == "fixed_risk":
            assert self.fixed_risk_config is not None
            # A contract stop opts a strategy into fixed-R exit simulation;
            # without one the position is held to settlement and its worst
            # case is the full premium (contract -> 0c), so stop_price_cents=0
            # and no exit-leg fee.
            stop_cents = decision.stop_price_cents
            has_stop = stop_cents is not None
            sized = size_validation_position(
                equity_usd=live_cash,
                entry_price_cents=decision.entry_price_cents,
                stop_price_cents=stop_cents if stop_cents is not None else 0,
                config=self.fixed_risk_config
                if has_stop
                else FixedRiskConfig(
                    risk_pct=self.fixed_risk_config.risk_pct,
                    max_position_pct=self.fixed_risk_config.max_position_pct,
                    fee_coefficient=self.fixed_risk_config.fee_coefficient,
                    include_exit_fee=False,
                    version=self.fixed_risk_config.version,
                ),
            )
            quantity = int(sized)
        else:
            quantity = size_binary_position(
                p_win=decision.fair_probability,
                cost_cents=decision.entry_price_cents,
                bankroll_usd=live_cash,
                kelly_fraction=self.kelly_fraction,
                max_position_pct=self.max_position_pct,
            )
        if quantity <= 0:
            return "no_fill"

        self.broker.set_current_bar(
            MarketBar(
                market_ticker=ticker,
                ts=fill_ts,
                yes_bid_low=candle.yes_bid_low,
                yes_bid_close=candle.yes_bid_close,
                yes_ask_high=candle.yes_ask_high,
                yes_ask_close=candle.yes_ask_close,
                volume=candle.volume,
                yes_bid_high=candle.yes_bid_high,
                yes_ask_low=candle.yes_ask_low,
            )
        )
        result = await self.broker.place_order(
            OrderRequest(market_ticker=ticker, side=pending.side, quantity=quantity)
        )
        if result.status != "filled":
            return "no_fill"

        # Entry gates are evaluated against the ACTUAL FILL, not the price
        # the strategy gated on at decision time (spec: backtest-engine
        # "Entry gates are evaluated against the actual fill"). A fill
        # outside the strategy's declared band is voided rather than
        # recorded — the fix for Phase 1's 18/64 (28%) out-of-band trades.
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
            self.broker.void_fill(ticker)
            logger.warning(
                "{}: fill at {}c rejected, outside entry band [{}, {}]",
                ticker,
                fill_price,
                decision.min_entry_price_cents,
                decision.max_entry_price_cents,
            )
            return "rejected_band"

        entry_ts_by_market[ticker] = fill_ts
        if decision.stop_price_cents is not None and decision.target_price_cents is not None:
            exit_levels_by_market[ticker] = (
                decision.stop_price_cents,
                decision.target_price_cents,
                pending.side,
            )
        self.session.flush()  # gives both the signal row and the trade row their ids
        trade_rows[ticker] = SimulatedTrade(
            backtest_run_id=run_id,
            signal_id=pending.signal_row.id,
            mode="backtest",
            market_ticker=ticker,
            side=pending.side,
            quantity=result.quantity,
            entry_price_cents=result.fill_price_cents or 0,
            entry_ts=fill_ts,
            status="open",
        )
        self.session.add(trade_rows[ticker])
        return "filled"

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

        # BRTI index history for the settlement-aware strategies (§4.1). One
        # series (BTC), loaded once; sliced per evaluation to the window the
        # settlement model consumes — the full 15-minute market lifetime plus
        # the 60 s reference average and the short-horizon trend lookback.
        brti_usable_ts, brti_readings = self._load_brti(start_ts, end_ts)

        timeline = sorted(set(candles_by_ts) | set(markets_by_close))
        equity_curve: list[tuple[int, float]] = []
        entry_ts_by_market: dict[str, int] = {}
        last_eval_ts: dict[str, int] = {}
        trade_rows: dict[str, SimulatedTrade] = {}
        # Entry decisions awaiting execution on the NEXT candle for their
        # market (kxbtc15m-validation-rebuild §2.1/§2.2). Keyed by ticker;
        # at most one pending order per market at a time (a market with an
        # order in flight is not re-evaluated). Drained in step 3 below.
        pending_by_market: dict[str, PendingEntry] = {}
        # Fixed-R exit levels (contract-cents) for markets whose entry decision
        # declared them (tasks.md 6.1/6.2 + 8.1's engine extension). A market
        # not in this dict rides to settlement exactly as before — this is
        # purely additive, opt-in per decision.
        # (stop_cents, target_cents, side)
        exit_levels_by_market: dict[str, tuple[int, int, Literal["yes", "no"]]] = {}
        evaluated = 0
        entered = 0
        fills_rejected_outside_band = 0
        dead_quotes = 0
        closed_early = 0
        pending_expired = 0

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
                    trade.entry_fee_usd = settlement.entry_fee_usd
                    trade.exit_fee_usd = settlement.exit_fee_usd
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
                        trade.entry_fee_usd = s.entry_fee_usd
                        trade.exit_fee_usd = s.exit_fee_usd
                        trade.fee_usd = s.fee_usd
                        trade.net_pnl_usd = s.net_pnl_usd

            # 3. execute entry orders decided at an EARLIER timestep, against
            # THIS timestep's candle for the same market (kxbtc15m-validation-
            # rebuild §2.1/§2.2: an order is eligible only on a market-data
            # event strictly after the one its decision consumed). Gates
            # (guard, throttle, liveness, entry band) and sizing are all
            # applied HERE, at fill time, against fill-time state — not at
            # decision time — so a market that went dead, or a guard that
            # HALTed, between decision and fill correctly blocks the entry.
            candles_here = candles_by_ts.get(ts, [])
            candle_by_ticker = {c.market_ticker: c for c in candles_here}
            for ticker, pending in list(pending_by_market.items()):
                if pending.close_ts <= ts:
                    # Market settled (or is settling this step) before any
                    # next candle arrived — the order never got a fill event.
                    del pending_by_market[ticker]
                    pending_expired += 1
                    continue
                fill_candle = candle_by_ticker.get(ticker)
                if fill_candle is None:
                    continue  # no market-data event yet; keep waiting
                del pending_by_market[ticker]
                filled = await self._execute_pending(
                    pending,
                    fill_candle,
                    ts,
                    run_id=run_row.id,
                    trade_rows=trade_rows,
                    entry_ts_by_market=entry_ts_by_market,
                    exit_levels_by_market=exit_levels_by_market,
                )
                if filled == "filled":
                    entered += 1
                    if self.throttle is not None:
                        self.throttle.record_entry(pending.series_ticker, ts)
                elif filled == "rejected_band":
                    fills_rejected_outside_band += 1
                elif filled == "dead_quote":
                    dead_quotes += 1

            # 4. equity + guard (open positions marked at entry cost)
            cash = await self.broker.get_account_balance()
            open_positions = await self.broker.get_open_positions()
            equity = cash + sum(p.quantity * p.avg_entry_price_cents / 100 for p in open_positions)
            equity_curve.append((ts, equity))
            self.guard.update(equity, ts=ts)

            # 5. evaluate open markets with a candle this timestep. A decision
            # that would enter is QUEUED here and executed on a LATER candle
            # (step 3 above) — never filled in the same bar its decision
            # consumed.
            for candle in candles_here:
                market = markets[candle.market_ticker]
                if market.close_ts <= ts or market.ticker in entry_ts_by_market:
                    continue
                if market.ticker in pending_by_market:
                    continue  # an order is already in flight for this market
                last = last_eval_ts.get(market.ticker)
                if last is not None and ts - last < self.eval_stride_s:
                    continue
                last_eval_ts[market.ticker] = ts
                symbol = SERIES_SYMBOL.get(market.series_ticker)
                if symbol is None:
                    continue
                hourly_ts, hourly_close = spot_hourly[symbol]
                spot_val = self._latest_before(hourly_ts, hourly_close, ts)
                daily_ts, daily_close = spot_daily[symbol]
                cutoff = bisect.bisect_left(daily_ts, ts)
                daily_history = daily_close[:cutoff]
                try:
                    vol = estimate_volatility(daily_history)
                except ValueError:
                    vol = None

                # The settlement-aware strategies (§4.1-4.4) consult only the
                # quote and BRTI, never spot/vol/trend. Rather than skip every
                # market when no SpotCandle history is archived (the validation
                # path does not collect one), fall through with sentinel
                # inputs — a strategy that DOES need spot already guards on
                # `spot > 0` / `vol_source` (e.g. crypto_mispricing).
                spot = spot_val if spot_val is not None else 0.0
                vol_annual = vol.vol_annual if vol is not None else 0.0
                vol_source = vol.source if vol is not None else "unavailable"

                # trend z-score: realized log-return over the lookback window,
                # normalized by the zero-drift model's expected scale (sigma*sqrt(t))
                trend_z: float | None = None
                spot_then = self._latest_before(hourly_ts, hourly_close, ts - self.trend_lookback_s)
                if (
                    spot_val is not None
                    and spot_then is not None
                    and spot_then > 0
                    and vol_annual > 0
                ):
                    lookback_years = self.trend_lookback_s / (365 * 24 * 3600)
                    trend_z = math.log(spot_val / spot_then) / (
                        vol_annual * math.sqrt(lookback_years)
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
                    vol_annual=vol_annual,
                    vol_source=vol_source,
                    trend_zscore=trend_z,
                    spot_bars=spot_bars,
                    brti_readings=self._brti_before(
                        brti_usable_ts, brti_readings, ts, window_s=_BRTI_SLICE_WINDOW_S
                    ),
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
                # A BUY that fails to declare a side-consistent win
                # probability is a strategy bug (kxbtc15m-validation-rebuild
                # §2.3: no default-certainty path). Reject it at decision
                # time — no point queuing an order that can never size.
                p_win = decision.fair_probability
                if p_win is None:
                    logger.warning(
                        "{}: {} decision from {} has no fair_probability; not entering",
                        market.ticker,
                        decision.action,
                        decision.strategy_name,
                    )
                    continue
                if not 0.0 <= p_win <= 1.0:
                    logger.warning(
                        "{}: {} fair_probability {} outside [0, 1]; not entering",
                        market.ticker,
                        decision.action,
                        p_win,
                    )
                    continue
                if decision.entry_price_cents is None:
                    continue
                # Queue the entry — it executes on the NEXT candle for this
                # market (step 3), not here. All fill-time gates (guard,
                # throttle, liveness, sizing, entry band) run at execution
                # against fill-time state, not now.
                side: Literal["yes", "no"] = (
                    "yes" if decision.action == Action.BUY_YES else "no"
                )
                pending_by_market[market.ticker] = PendingEntry(
                    market_ticker=market.ticker,
                    series_ticker=market.series_ticker,
                    decided_ts=ts,
                    close_ts=market.close_ts,
                    decision=decision,
                    side=side,
                    signal_row=signal_row,
                )

        # any entry still queued when history ends never got a fill event
        pending_expired += len(pending_by_market)

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
            "{} dead-quote markets skipped, {} queued entries expired unfilled "
            "(no next candle before market close)",
            run_row.id,
            evaluated,
            entered,
            len(self.broker.settlements),
            closed_early,
            fills_rejected_outside_band,
            dead_quotes,
            pending_expired,
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
