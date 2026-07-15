"""Backtest metrics — built to make fee-adjusted reality unmissable.

The headline table always shows achieved win rate NEXT TO the fee-adjusted
breakeven win rate: v1's "51% win rate" looked like success and was a net
loser; here that comparison is computed for you, per segment.

Breakeven win probability at cost c with fee f on net winnings:
    p_be = c / ((1 - c)(1 - f) + c)
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from kalshi_bot.execution.backtest_broker import KALSHI_FEE_RATE, Settlement

HOURS_PER_YEAR = 365 * 24


def breakeven_win_rate(cost_dollars: float, fee_rate: float = KALSHI_FEE_RATE) -> float:
    return cost_dollars / ((1.0 - cost_dollars) * (1.0 - fee_rate) + cost_dollars)


@dataclass(frozen=True)
class SegmentMetrics:
    label: str  # "train" | "test"
    n_trades: int
    wins: int
    win_rate: float | None
    breakeven_win_rate_avg: float | None  # at the segment's average entry cost
    win_rate_margin: float | None  # achieved - breakeven; NEGATIVE = losing after fees
    gross_pnl_usd: float
    fees_usd: float
    net_pnl_usd: float
    avg_entry_cost_cents: float | None
    sharpe_hourly_equity: float | None  # annualized from hourly equity returns
    sortino_hourly_equity: float | None
    max_drawdown_pct: float | None

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        if self.n_trades == 0:
            return f"[{self.label}] no trades"
        sharpe = "n/a" if self.sharpe_hourly_equity is None else f"{self.sharpe_hourly_equity:.2f}"
        mdd = "n/a" if self.max_drawdown_pct is None else f"{self.max_drawdown_pct:.1%}"
        return (
            f"[{self.label}] trades={self.n_trades} "
            f"win_rate={self.win_rate:.1%} vs breakeven={self.breakeven_win_rate_avg:.1%} "
            f"(margin {self.win_rate_margin:+.1%}) "
            f"net_pnl=${self.net_pnl_usd:+.2f} (fees ${self.fees_usd:.2f}) "
            f"sharpe={sharpe} max_dd={mdd}"
        )


def _annualized_ratio(returns: np.ndarray, *, downside_only: bool) -> float | None:
    if len(returns) < 2:
        return None
    mean = float(np.mean(returns))
    if downside_only:
        downside = returns[returns < 0]
        if len(downside) == 0:
            return None if mean <= 0 else float("inf")
        denom = float(np.sqrt(np.mean(downside**2)))
    else:
        denom = float(np.std(returns, ddof=1))
    if denom == 0:
        return None
    return mean / denom * math.sqrt(HOURS_PER_YEAR)


def max_drawdown(equity: np.ndarray) -> float | None:
    if len(equity) < 2:
        return None
    peaks = np.maximum.accumulate(equity)
    drawdowns = 1.0 - equity / peaks
    return float(np.max(drawdowns))


def compute_segment_metrics(
    label: str,
    settlements: list[Settlement],
    equity_curve: list[tuple[int, float]],
) -> SegmentMetrics:
    """Metrics for one segment. `equity_curve` is (ts, equity) sampled hourly
    within the segment; settlements are those whose ENTRY fell in the segment."""
    n = len(settlements)
    wins = sum(1 for s in settlements if s.won)
    gross = sum(s.gross_pnl_usd for s in settlements)
    fees = sum(s.fee_usd for s in settlements)
    net = sum(s.net_pnl_usd for s in settlements)

    if n > 0:
        avg_cost_cents = float(np.mean([s.entry_price_cents for s in settlements]))
        be = breakeven_win_rate(avg_cost_cents / 100)
        win_rate = wins / n
        margin = win_rate - be
    else:
        avg_cost_cents = None
        be = None
        win_rate = None
        margin = None

    equity = np.asarray([e for _, e in equity_curve], dtype=float)
    if len(equity) >= 2 and np.all(equity > 0):
        returns = np.diff(np.log(equity))
        sharpe = _annualized_ratio(returns, downside_only=False)
        sortino = _annualized_ratio(returns, downside_only=True)
        mdd = max_drawdown(equity)
    else:
        sharpe = sortino = mdd = None

    return SegmentMetrics(
        label=label,
        n_trades=n,
        wins=wins,
        win_rate=win_rate,
        breakeven_win_rate_avg=be,
        win_rate_margin=margin,
        gross_pnl_usd=gross,
        fees_usd=fees,
        net_pnl_usd=net,
        avg_entry_cost_cents=avg_cost_cents,
        sharpe_hourly_equity=sharpe,
        sortino_hourly_equity=sortino,
        max_drawdown_pct=mdd,
    )
