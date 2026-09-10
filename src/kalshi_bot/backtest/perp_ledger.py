"""Perpetual-futures strategy ledger, metrics, and promotion — deliberately
SEPARATE from the binary-event reporting path (kxbtc15m-validation-rebuild
§5.1, design decision "Keep perps on an independent safety and economics
track").

design.md is explicit that "perp entries, funding, liquidation/margin
exposure, and exits are evaluated in a SEPARATE ledger and gate", and that
"a binary contract is not accepted as a linear funding hedge". So this
module does not import or reuse `backtest/report.py`, `backtest/metrics.py`,
or `promotion_gate.py` — those speak binary settlement, Brier score, and
win-rate, none of which apply to a mark-to-market perp position.

A perp position's economics:
  - PnL = size * (exit_mark - entry_mark)   (size signed: + long, - short)
  - funding accrues every funding interval: -sign(size) is charged/credited
    `position_notional * funding_rate` (longs pay positive funding)
  - taker fees on entry and exit
  - the risk that dominates is LIQUIDATION, not an adverse binary outcome —
    so the metrics here foreground leverage used and the minimum distance to
    liquidation reached, not a win rate.

Nothing here places orders or drives a simulation; it is the accounting +
reporting layer a perp backtest/paper run feeds its fills and funding
events into.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class PerpFill:
    """One executed perp order. `size` is signed contracts: positive opens/
    increases a long, negative a short. `mark_price` is the fill price in
    USD per contract-unit of the reference index."""

    ts: int
    size: float
    mark_price: float
    fee_usd: float


@dataclass(frozen=True)
class FundingEvent:
    """One funding settlement while a position was open. `payment_usd` is
    SIGNED from the account's perspective: negative = the account paid
    funding, positive = the account received it."""

    ts: int
    funding_rate: float
    position_notional_usd: float
    payment_usd: float


@dataclass(frozen=True)
class PerpTrade:
    """A round-trip perp position: one or more opening fills, funding while
    held, one or more closing fills. Kept flat (a single net entry / net
    exit) for the initial ledger — partial scaling is a later concern."""

    symbol: str
    entry_ts: int
    exit_ts: int
    size: float  # signed; the net position size held
    entry_mark: float
    exit_mark: float
    entry_fee_usd: float
    exit_fee_usd: float
    funding_events: tuple[FundingEvent, ...] = ()
    max_leverage_used: float | None = None
    min_distance_to_liquidation: float | None = None
    """Smallest (mark - liquidation_price)/mark reached while the position
    was open, as a fraction. Small = came close to being liquidated. None
    when not tracked."""

    @property
    def gross_pnl_usd(self) -> float:
        return self.size * (self.exit_mark - self.entry_mark)

    @property
    def funding_pnl_usd(self) -> float:
        return sum(e.payment_usd for e in self.funding_events)

    @property
    def fees_usd(self) -> float:
        return self.entry_fee_usd + self.exit_fee_usd

    @property
    def net_pnl_usd(self) -> float:
        return self.gross_pnl_usd + self.funding_pnl_usd - self.fees_usd

    @property
    def entry_notional_usd(self) -> float:
        return abs(self.size) * self.entry_mark


@dataclass(frozen=True)
class PerpLedgerMetrics:
    """Perp-specific segment metrics. Note the absence of a win-rate /
    breakeven-win-rate / Brier: those are binary-settlement concepts. The
    perp analogues are the return distribution and, above all, how close
    the book came to liquidation."""

    n_trades: int
    net_pnl_usd: float
    gross_pnl_usd: float
    funding_pnl_usd: float
    fees_usd: float
    funding_share_of_net: float | None
    """funding_pnl / net_pnl — for a funding-carry strategy this should be
    ~1 (the edge IS the funding); for a directional perp strategy it should
    be small. A carry strategy whose net PnL is mostly PRICE move, not
    funding, is mislabelled — see §5.2."""
    avg_return_on_notional: float | None
    worst_trade_pnl_usd: float | None
    max_leverage_used: float | None
    min_distance_to_liquidation: float | None
    """The single closest any trade came to liquidation across the segment.
    A promotion gate on perps must look at this, not just PnL."""
    n_liquidations: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def compute_perp_metrics(trades: list[PerpTrade]) -> PerpLedgerMetrics:
    if not trades:
        return PerpLedgerMetrics(
            n_trades=0,
            net_pnl_usd=0.0,
            gross_pnl_usd=0.0,
            funding_pnl_usd=0.0,
            fees_usd=0.0,
            funding_share_of_net=None,
            avg_return_on_notional=None,
            worst_trade_pnl_usd=None,
            max_leverage_used=None,
            min_distance_to_liquidation=None,
            n_liquidations=0,
        )
    net = sum(t.net_pnl_usd for t in trades)
    gross = sum(t.gross_pnl_usd for t in trades)
    funding = sum(t.funding_pnl_usd for t in trades)
    fees = sum(t.fees_usd for t in trades)
    returns = [t.net_pnl_usd / t.entry_notional_usd for t in trades if t.entry_notional_usd > 0]
    levs = [t.max_leverage_used for t in trades if t.max_leverage_used is not None]
    dists = [
        t.min_distance_to_liquidation for t in trades if t.min_distance_to_liquidation is not None
    ]
    return PerpLedgerMetrics(
        n_trades=len(trades),
        net_pnl_usd=net,
        gross_pnl_usd=gross,
        funding_pnl_usd=funding,
        fees_usd=fees,
        funding_share_of_net=(funding / net) if net != 0 else None,
        avg_return_on_notional=(sum(returns) / len(returns)) if returns else None,
        worst_trade_pnl_usd=min(t.net_pnl_usd for t in trades),
        max_leverage_used=max(levs) if levs else None,
        min_distance_to_liquidation=min(dists) if dists else None,
        n_liquidations=sum(
            1
            for t in trades
            if t.min_distance_to_liquidation is not None and t.min_distance_to_liquidation <= 0.0
        ),
    )


# --- independent perp promotion gate -------------------------------------


@dataclass(frozen=True)
class PerpPromotionPolicy:
    """Separate from `promotion_gate.PromotionPolicy` on purpose (§5.1:
    "split ... promotion configuration"). Perps are only enabled after
    their OWN gate AND — separately — the event-contract gate both pass
    (design.md migration step 5)."""

    min_trades: int = 30
    min_net_expectancy_usd: float = 0.0
    min_distance_to_liquidation: float = 0.15
    """No trade may have come within 15% of its liquidation price. A perp
    strategy that only makes money by riding close to liquidation is not
    promotable regardless of PnL."""
    max_leverage: float = 2.0  # design.md's default cap; hard ceiling 3x elsewhere
    forbid_any_liquidation: bool = True


@dataclass(frozen=True)
class PerpPromotionDecision:
    passed: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "reasons": list(self.reasons)}


def evaluate_perp_promotion(
    metrics: PerpLedgerMetrics, policy: PerpPromotionPolicy | None = None
) -> PerpPromotionDecision:
    policy = policy or PerpPromotionPolicy()
    reasons: list[str] = []
    if metrics.n_trades < policy.min_trades:
        reasons.append(f"only {metrics.n_trades} perp trades; need {policy.min_trades}")
    if metrics.net_pnl_usd <= policy.min_net_expectancy_usd * max(metrics.n_trades, 1):
        reasons.append("perp net PnL does not clear the expectancy threshold")
    if policy.forbid_any_liquidation and metrics.n_liquidations > 0:
        reasons.append(f"{metrics.n_liquidations} trade(s) were liquidated")
    if (
        metrics.min_distance_to_liquidation is not None
        and metrics.min_distance_to_liquidation < policy.min_distance_to_liquidation
    ):
        reasons.append(
            f"came within {metrics.min_distance_to_liquidation:.2%} of liquidation; "
            f"floor is {policy.min_distance_to_liquidation:.2%}"
        )
    if metrics.max_leverage_used is not None and metrics.max_leverage_used > policy.max_leverage:
        reasons.append(
            f"max leverage {metrics.max_leverage_used:.2f}x exceeds {policy.max_leverage:.2f}x"
        )
    return PerpPromotionDecision(not reasons, tuple(reasons))


def build_perp_report(
    trades: list[PerpTrade],
    *,
    coverage: dict[str, object] | None = None,
    policy: PerpPromotionPolicy | None = None,
) -> dict[str, object]:
    """Emit a perp-only report with economics, liquidation, coverage, and verdict."""
    metrics = compute_perp_metrics(trades)
    decision = evaluate_perp_promotion(metrics, policy)
    return {
        "domain": "perp",
        "metrics": metrics.to_dict(),
        "coverage": coverage or {},
        "promotion": decision.to_dict(),
    }


__all__ = [
    "FundingEvent",
    "PerpFill",
    "PerpLedgerMetrics",
    "PerpPromotionDecision",
    "PerpPromotionPolicy",
    "PerpTrade",
    "build_perp_report",
    "compute_perp_metrics",
    "evaluate_perp_promotion",
]
