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
from collections import defaultdict
from dataclasses import dataclass

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.backtest.metrics import SegmentMetrics, compute_segment_metrics
from kalshi_bot.execution.backtest_broker import BacktestBroker, MarketBar, Settlement
from kalshi_bot.execution.broker_protocol import OrderRequest
from kalshi_bot.risk.drawdown_guard import DrawdownGuard
from kalshi_bot.risk.kelly import size_binary_position
from kalshi_bot.signals.volatility import estimate_volatility
from kalshi_bot.storage.models import BacktestRun, Candle, KalshiMarket, SimulatedTrade, SpotCandle
from kalshi_bot.storage.records import record_signal
from kalshi_bot.strategy.base import Action, StrategyContext, StrategyProtocol

SERIES_SYMBOL = {
    "KXBTC": "BTC-USD",
    "KXBTCD": "BTC-USD",
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
    ) -> None:
        self.strategy = strategy
        self.broker = broker
        self.session = session
        self.starting_cash = starting_cash_usd
        self.kelly_fraction = kelly_fraction
        self.max_position_pct = max_position_pct
        self.guard = guard

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
                Candle.period_minutes == 60,
            )
        ).scalars():
            if candle.market_ticker in markets:
                candles_by_ts[candle.end_period_ts].append(candle)

        markets_by_close: dict[int, list[KalshiMarket]] = defaultdict(list)
        for m in markets.values():
            markets_by_close[m.close_ts].append(m)

        spot_hourly: dict[str, tuple[list[int], list[float]]] = {}
        spot_daily: dict[str, tuple[list[int], list[float]]] = {}
        for symbol in set(SERIES_SYMBOL.values()):
            spot_hourly[symbol] = self._load_spot(symbol, 60)
            spot_daily[symbol] = self._load_spot(symbol, 1440)

        timeline = sorted(set(candles_by_ts) | set(markets_by_close))
        equity_curve: list[tuple[int, float]] = []
        entry_ts_by_market: dict[str, int] = {}
        trade_rows: dict[str, SimulatedTrade] = {}
        evaluated = 0
        entered = 0

        for ts in timeline:
            # 1. settle everything that closed at/by this timestep
            for market in markets_by_close.get(ts, []):
                self.broker.settle_market(market.ticker, market.result or "", ts)
                trade = trade_rows.get(market.ticker)
                if trade is not None and self.broker.settlements:
                    s = self.broker.settlements[-1]
                    if s.market_ticker == market.ticker:
                        trade.exit_ts = ts
                        trade.exit_price_cents = 100 if s.won else 0
                        trade.status = "settled_won" if s.won else "settled_lost"
                        trade.gross_pnl_usd = s.gross_pnl_usd
                        trade.fee_usd = s.fee_usd
                        trade.net_pnl_usd = s.net_pnl_usd

            # 2. equity + guard (open positions marked at entry cost)
            cash = await self.broker.get_account_balance()
            open_positions = await self.broker.get_open_positions()
            equity = cash + sum(p.quantity * p.avg_entry_price_cents / 100 for p in open_positions)
            equity_curve.append((ts, equity))
            self.guard.update(equity)

            # 3. evaluate open markets with a candle this hour
            for candle in candles_by_ts.get(ts, []):
                market = markets[candle.market_ticker]
                if market.close_ts <= ts or market.ticker in entry_ts_by_market:
                    continue
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
                )
                decision = self.strategy.evaluate(context)
                evaluated += 1
                signal_row = record_signal(
                    self.session, decision, context, mode="backtest", backtest_run_id=run_row.id
                )

                if decision.action == Action.HOLD:
                    continue
                if not self.guard.allows_new_entries():
                    continue

                p_win = (
                    decision.bs_probability
                    if decision.action == Action.BUY_YES
                    else 1.0 - (decision.bs_probability or 0.0)
                )
                if p_win is None or decision.entry_price_cents is None:
                    continue
                quantity = size_binary_position(
                    p_win=p_win,
                    cost_cents=decision.entry_price_cents,
                    bankroll_usd=equity,
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
                    )
                )
                side = "yes" if decision.action == Action.BUY_YES else "no"
                result = await self.broker.place_order(
                    OrderRequest(market_ticker=market.ticker, side=side, quantity=quantity)
                )
                if result.status != "filled":
                    continue
                entered += 1
                entry_ts_by_market[market.ticker] = ts
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
            "backtest run {} complete: {} evaluations, {} entries, {} settlements",
            run_row.id,
            evaluated,
            entered,
            len(self.broker.settlements),
        )
        return BacktestResult(run_id=run_row.id, train=train, test=test, final_equity=final_equity)
