"""Backtest metrics — built to make fee-adjusted reality unmissable.

The headline table always shows achieved win rate NEXT TO the fee-adjusted
breakeven win rate: v1's "51% win rate" looked like success and was a net
loser; here that comparison is computed for you, per segment.

Breakeven win probability, corrected fee model (fee charged once, at entry,
win or lose — not a cut of net winnings at settlement, see signals/fees.py):
held to settlement, a contract bought at cost P (dollars) with entry fee f
pays $1 on a win, $0 on a loss. EV=0 at:
    p_win*(1-P-f) - (1-p_win)*(P+f) = 0  =>  p_be = P + f
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass

import numpy as np

from kalshi_bot.execution.backtest_broker import Settlement
from kalshi_bot.signals.fees import (
    TAKER_FEE_COEFFICIENT,
    entry_fee_dollars,
    entry_fee_rate_at_price,
)

HOURS_PER_YEAR = 365 * 24


@dataclass(frozen=True)
class TradeEconomics:
    """Cost-aware economics for one proposed binary-contract trade."""

    entry_price_dollars: float
    stop_price_dollars: float
    target_price_dollars: float
    quantity: float
    entry_fee_usd: float
    stop_exit_fee_usd: float
    target_exit_fee_usd: float
    breakeven_win_rate: float
    expectancy_usd: float
    modeled_win_probability: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def trade_economics(
    *,
    entry_price_dollars: float,
    stop_price_dollars: float,
    target_price_dollars: float,
    quantity: float,
    modeled_win_probability: float,
    fee_rate: float = TAKER_FEE_COEFFICIENT,
    exit_on_stop: bool = True,
) -> TradeEconomics:
    """Derive breakeven and EV from this trade's prices and both legs.

    Prices are for the held side (YES or NO).  The stop and target are
    executable exit prices, not spot or settlement proxies.
    """
    if quantity <= 0 or not 0 <= modeled_win_probability <= 1:
        raise ValueError("quantity must be positive and probability must be in [0, 1]")
    if not 0 < entry_price_dollars < 1:
        raise ValueError("entry price must be in (0, 1)")
    if not 0 <= stop_price_dollars <= 1 or not 0 <= target_price_dollars <= 1:
        raise ValueError("stop and target prices must be in [0, 1]")
    entry_fee = entry_fee_rate_at_price(entry_price_dollars, coefficient=fee_rate) * quantity
    stop_fee = (
        entry_fee_rate_at_price(stop_price_dollars, coefficient=fee_rate) * quantity
        if exit_on_stop
        else 0.0
    )
    target_fee = entry_fee_rate_at_price(target_price_dollars, coefficient=fee_rate) * quantity
    win_pnl = (target_price_dollars - entry_price_dollars) * quantity - entry_fee - target_fee
    loss_pnl = (stop_price_dollars - entry_price_dollars) * quantity - entry_fee - stop_fee
    denominator = win_pnl - loss_pnl
    breakeven = (-loss_pnl / denominator) if denominator > 0 else 1.0
    expectancy = modeled_win_probability * win_pnl + (1 - modeled_win_probability) * loss_pnl
    return TradeEconomics(
        entry_price_dollars, stop_price_dollars, target_price_dollars, quantity,
        entry_fee, stop_fee, target_fee, breakeven, expectancy, modeled_win_probability,
    )


def brier_score(probabilities: Sequence[float], outcomes: Sequence[bool | int]) -> float | None:
    """Mean squared probability error; returns ``None`` for no observations."""
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have equal length")
    if not probabilities:
        return None
    if any(not 0 <= p <= 1 for p in probabilities):
        raise ValueError("probabilities must be in [0, 1]")
    return float(np.mean([(p - int(y)) ** 2 for p, y in zip(probabilities, outcomes, strict=True)]))


def day_block_bootstrap_ci(
    values: Iterable[tuple[int, float]], *, samples: int = 2_000,
    confidence: float = 0.95, seed: int = 0,
) -> tuple[float, float] | None:
    """Bootstrap a mean by UTC day blocks, retaining intraday dependence."""
    grouped: dict[int, list[float]] = {}
    for ts, value in values:
        grouped.setdefault(ts // 86_400, []).append(float(value))
    if not grouped:
        return None
    if samples < 1 or not 0 < confidence < 1:
        raise ValueError("samples must be positive and confidence must be in (0, 1)")
    rng = np.random.default_rng(seed)
    blocks = list(grouped.values())
    means = np.empty(samples)
    for i in range(samples):
        chosen = rng.integers(0, len(blocks), size=len(blocks))
        means[i] = np.mean(np.concatenate([blocks[j] for j in chosen]))
    alpha = (1 - confidence) / 2
    return float(np.quantile(means, alpha)), float(np.quantile(means, 1 - alpha))


def breakeven_win_rate(cost_dollars: float, fee_rate: float = TAKER_FEE_COEFFICIENT) -> float:
    return cost_dollars + entry_fee_rate_at_price(cost_dollars, coefficient=fee_rate)


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

    # tasks.md 8.2: metrics beyond win rate and PnL — Phase 1's run #8 was
    # 122% trade concentration (the top 10 trades alone exceeded total
    # profit, meaning the "average" trade was actually a loser propped up
    # by a handful of outliers).
    top10_concentration_pct: float | None
    """Top-10 winning trades' gross PnL as a fraction of TOTAL gross profit
    (sum of only the winning trades' PnL, not net). >1.0 means the top 10
    alone exceed total profit — the rest of the book is a net drag. None
    when there are fewer than 10 trades (undefined) or zero total profit."""
    max_consecutive_losses: int
    r_multiples: tuple[float, ...]
    """Each settled trade's realized PnL expressed as a multiple of its own
    risk (net_pnl_usd / (entry_price_cents/100 * quantity) for a trade with
    no fixed-R exit — i.e. R = the full stake, since without a declared stop
    the entire position is at risk). Empty tuple if there are no trades."""
    net_pnl_at_flat_sizing_usd: float
    """The segment's net PnL recomputed at a single fixed contract per
    trade (tasks.md 8.2: "results under flat sizing") — a real check
    against Kelly-compounding manufacturing apparent edge purely from
    position-size variation."""

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        if self.n_trades == 0:
            return f"[{self.label}] no trades"
        sharpe = "n/a" if self.sharpe_hourly_equity is None else f"{self.sharpe_hourly_equity:.2f}"
        mdd = "n/a" if self.max_drawdown_pct is None else f"{self.max_drawdown_pct:.1%}"
        conc = (
            "n/a"
            if self.top10_concentration_pct is None
            else f"{self.top10_concentration_pct:.0%}"
        )
        return (
            f"[{self.label}] trades={self.n_trades} "
            f"win_rate={self.win_rate:.1%} vs breakeven={self.breakeven_win_rate_avg:.1%} "
            f"(margin {self.win_rate_margin:+.1%}) "
            f"net_pnl=${self.net_pnl_usd:+.2f} (fees ${self.fees_usd:.2f}) "
            f"sharpe={sharpe} max_dd={mdd} "
            f"top10_concentration={conc} max_consec_losses={self.max_consecutive_losses} "
            f"flat_sizing_net_pnl=${self.net_pnl_at_flat_sizing_usd:+.2f}"
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


def top_n_concentration(settlements: list[Settlement], *, n: int = 10) -> float | None:
    """Top-`n` trades' NET PnL as a fraction of the segment's TOTAL net
    profit (all settlements, wins and losses together) — this is what
    "top-10 trades were 122% of profit" (Phase 1 run #8) actually means:
    the top 10 winners alone exceeded the strategy's entire realized profit,
    so every other trade combined was a net drag. None if fewer than `n`
    trades exist at all, or if total net profit is <= 0 (the ratio is
    undefined there — a concentration percentage of a non-positive number
    doesn't mean "healthy," it means the whole book lost)."""
    if len(settlements) < n:
        return None
    total_net_profit = sum(s.net_pnl_usd for s in settlements)
    if total_net_profit <= 0:
        return None
    top_n_net = sum(sorted((s.net_pnl_usd for s in settlements), reverse=True)[:n])
    return top_n_net / total_net_profit


def max_consecutive_losses(settlements: list[Settlement]) -> int:
    """Longest run of consecutive losing trades, ordered by entry time (the
    order they actually occurred in, not settlement order which can differ
    under early exits)."""
    ordered = sorted(settlements, key=lambda s: s.entry_ts)
    longest = current = 0
    for s in ordered:
        if not s.won:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def r_multiples(settlements: list[Settlement]) -> tuple[float, ...]:
    """Each trade's net PnL as a multiple of its own risk. Without a
    per-trade recorded stop distance (Settlement doesn't carry one — see
    `SimulatedTrade` for stop/target if a caller needs the true fixed-R
    figure), R here is the full stake (entry_price_cents/100 * quantity):
    the maximum loss an event-contract position can take is capped at its
    own cost, so "1R" = "lost the whole stake" is the natural unit when no
    tighter stop was declared."""
    result = []
    for s in settlements:
        stake = (s.entry_price_cents / 100) * s.quantity
        if stake <= 0:
            continue
        result.append(s.net_pnl_usd / stake)
    return tuple(result)


def flat_sizing_net_pnl_usd(settlements: list[Settlement], *, flat_quantity: int = 1) -> float:
    """Reconstruct net PnL as if every trade had used a FIXED contract count
    (`flat_quantity`) instead of whatever variable sizing the run actually
    used (tasks.md 8.2: "results under flat sizing"). This is a real check
    against Kelly-style compounding manufacturing apparent edge purely from
    position-size variation rather than genuine per-trade edge — the same
    failure mode `kelly.py`'s docstring already documents (a $172 position
    on a $130 bankroll from compounding).

    Reuses each trade's own entry price and fee RATE (fee scales with
    quantity, so it's recomputed at `flat_quantity`, not carried over from
    the original trade's fee_usd) — everything else about the trade
    (win/loss, entry price) is held fixed; only the size changes."""
    total = 0.0
    for s in settlements:
        cost_dollars = s.entry_price_cents / 100
        fee = entry_fee_dollars(s.entry_price_cents, flat_quantity)
        gross = (1.0 - cost_dollars) * flat_quantity if s.won else -cost_dollars * flat_quantity
        total += gross - fee
    return total


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
        top10_concentration_pct=top_n_concentration(settlements),
        max_consecutive_losses=max_consecutive_losses(settlements),
        r_multiples=r_multiples(settlements),
        net_pnl_at_flat_sizing_usd=flat_sizing_net_pnl_usd(settlements),
    )
