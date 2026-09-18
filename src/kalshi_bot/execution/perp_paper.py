"""Causal side-aware linear perpetual paper execution (no exchange orders)."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.storage import PerpPaperEvent, PerpPaperPosition


class PerpPaperError(ValueError):
    pass


@dataclass(frozen=True)
class PerpQuote:
    bid: float | None
    ask: float | None
    observed_at: int
    available_at: int
    reference: dict[str, object]


@dataclass(frozen=True)
class PerpOrder:
    signed_quantity: float
    tick_size: float
    minimum_size: float
    multiplier: float
    fee_rate: float


@dataclass(frozen=True)
class PerpPaperFill:
    signed_quantity: float
    fill_price: float
    fee_usd: float
    observed_at: int
    quote_reference: dict[str, object]


@dataclass(frozen=True)
class PerpBracket:
    stop_loss: float
    take_profit: float


def validate_bracket(bracket: PerpBracket, *, entry_price: float, signed_quantity: float) -> None:
    if signed_quantity == 0 or bracket.stop_loss <= 0 or bracket.take_profit <= 0:
        raise PerpPaperError("invalid_bracket")
    if signed_quantity > 0 and not bracket.stop_loss < entry_price < bracket.take_profit:
        raise PerpPaperError("long_bracket_order")
    if signed_quantity < 0 and not bracket.take_profit < entry_price < bracket.stop_loss:
        raise PerpPaperError("short_bracket_order")


def bracket_exit(bracket: PerpBracket, *, signed_quantity: float, mark_price: float) -> str | None:
    if signed_quantity > 0:
        return (
            "stop_loss"
            if mark_price <= bracket.stop_loss
            else ("take_profit" if mark_price >= bracket.take_profit else None)
        )
    return (
        "stop_loss"
        if mark_price >= bracket.stop_loss
        else ("take_profit" if mark_price <= bracket.take_profit else None)
    )


def fill_perp_order(order: PerpOrder, quote: PerpQuote, *, decision_ts: int) -> PerpPaperFill:
    if order.signed_quantity == 0 or abs(order.signed_quantity) < order.minimum_size:
        raise PerpPaperError("minimum_size")
    if order.tick_size <= 0 or order.multiplier <= 0 or order.fee_rate < 0:
        raise PerpPaperError("invalid_contract_parameters")
    if quote.available_at > decision_ts:
        raise PerpPaperError("stale_or_unavailable_quote")
    price = quote.ask if order.signed_quantity > 0 else quote.bid
    if price is None or price <= 0:
        raise PerpPaperError("one_sided_quote")
    ticks = price / order.tick_size
    if not isclose(ticks, round(ticks), abs_tol=1e-8):
        raise PerpPaperError("off_tick_quote")
    fee = abs(order.signed_quantity) * order.multiplier * price * order.fee_rate
    return PerpPaperFill(order.signed_quantity, price, fee, quote.observed_at, quote.reference)


@dataclass(frozen=True)
class PerpAccountState:
    collateral_usd: float
    signed_quantity: float
    entry_price: float
    multiplier: float
    realized_pnl_usd: float = 0.0
    funding_pnl_usd: float = 0.0
    fees_usd: float = 0.0


@dataclass(frozen=True)
class PerpMarkToMarket:
    equity_usd: float
    unrealized_pnl_usd: float
    notional_usd: float
    leverage: float | None
    liquidation_distance: float | None


def mark_to_market(
    state: PerpAccountState, *, mark_price: float, liquidation_price: float | None = None
) -> PerpMarkToMarket:
    if mark_price <= 0 or state.multiplier <= 0:
        raise PerpPaperError("invalid_mark")
    unrealized = state.signed_quantity * state.multiplier * (mark_price - state.entry_price)
    equity = (
        state.collateral_usd
        + state.realized_pnl_usd
        + state.funding_pnl_usd
        - state.fees_usd
        + unrealized
    )
    notional = abs(state.signed_quantity) * state.multiplier * mark_price
    leverage = notional / equity if equity > 0 else None
    distance = None
    if liquidation_price is not None:
        distance = (
            (mark_price - liquidation_price) / mark_price
            if state.signed_quantity > 0
            else (liquidation_price - mark_price) / mark_price
        )
    return PerpMarkToMarket(equity, unrealized, notional, leverage, distance)


def realized_funding(
    *, signed_quantity: float, multiplier: float, mark_price: float, funding_rate: float
) -> float:
    """Account PnL: positive funding charges longs and credits shorts."""
    return -signed_quantity * multiplier * mark_price * funding_rate


# --------------------------------------------------------------------------
# Leverage / liquidation / bracket / halt safety (§9.5)
# --------------------------------------------------------------------------

DEFAULT_MAX_LEVERAGE = 2.0
ABSOLUTE_MAX_LEVERAGE = 3.0


@dataclass(frozen=True)
class LeverageCheck:
    ok: bool
    leverage: float
    reason: str | None = None


def check_entry_leverage(
    *,
    signed_quantity: float,
    multiplier: float,
    price: float,
    collateral_usd: float,
    max_leverage: float = DEFAULT_MAX_LEVERAGE,
) -> LeverageCheck:
    """Reject an entry whose notional/collateral exceeds the cap.

    The cap is clamped to the absolute 3x ceiling regardless of what a caller
    passes, so a misconfigured registry cannot widen it.
    """
    cap = min(max(max_leverage, 0.0), ABSOLUTE_MAX_LEVERAGE)
    if collateral_usd <= 0:
        return LeverageCheck(False, float("inf"), "no_collateral")
    notional = abs(signed_quantity) * multiplier * price
    leverage = notional / collateral_usd
    if leverage > cap + 1e-9:
        return LeverageCheck(False, leverage, "leverage_or_minimum_size")
    return LeverageCheck(True, leverage, None)


def liquidation_price(
    *,
    signed_quantity: float,
    entry_price: float,
    multiplier: float,
    collateral_usd: float,
    maintenance_margin_rate: float = 0.005,
) -> float | None:
    """Conservative liquidation estimate: the mark at which equity falls to
    the maintenance-margin requirement. Returns None for a flat position."""
    if signed_quantity == 0 or multiplier <= 0 or entry_price <= 0:
        return None
    qty_abs = abs(signed_quantity)
    # equity(mark) = collateral + signed_qty*mult*(mark-entry)
    # maintenance(mark) = maint_rate * qty_abs*mult*mark
    # solve equity == maintenance
    denom = signed_quantity * multiplier - (
        maintenance_margin_rate * qty_abs * multiplier * (1 if signed_quantity > 0 else -1)
    )
    # For a long: equity decreasing in (entry-mark); solve directly.
    if signed_quantity > 0:
        # collateral + qty*mult*(mark-entry) = maint_rate*qty*mult*mark
        # mark*(qty*mult - maint_rate*qty*mult) = qty*mult*entry - collateral
        k = qty_abs * multiplier
        px = (k * entry_price - collateral_usd) / (k * (1 - maintenance_margin_rate))
    else:
        k = qty_abs * multiplier
        px = (k * entry_price + collateral_usd) / (k * (1 + maintenance_margin_rate))
    _ = denom  # kept for readability of the derivation above
    return px if px > 0 else None


@dataclass(frozen=True)
class PerpCloseResult:
    exit_price: float
    realized_pnl_usd: float
    funding_pnl_usd: float
    fees_usd: float
    reason: str
    quote_reference: dict[str, object]


def close_perp_position(
    *,
    signed_quantity: float,
    entry_price: float,
    multiplier: float,
    fee_rate: float,
    entry_fee_usd: float,
    funding_pnl_usd: float,
    exit_price: float,
    reason: str,
    quote_reference: dict[str, object] | None = None,
) -> PerpCloseResult:
    """Side-aware exit accounting. `exit_price` is the fill the caller already
    resolved (bracket level, forced-close mark, or opposing quote)."""
    if multiplier <= 0 or exit_price <= 0:
        raise PerpPaperError("invalid_close")
    price_pnl = signed_quantity * multiplier * (exit_price - entry_price)
    exit_fee = abs(signed_quantity) * multiplier * exit_price * fee_rate
    fees = entry_fee_usd + exit_fee
    return PerpCloseResult(
        exit_price=exit_price,
        realized_pnl_usd=price_pnl,
        funding_pnl_usd=funding_pnl_usd,
        fees_usd=fees,
        reason=reason,
        quote_reference=quote_reference or {},
    )


@dataclass(frozen=True)
class PerpStepDecision:
    """What a single mark/quote tick implies for an open position."""

    action: str  # "hold" | "close"
    reason: str | None
    exit_price: float | None = None


def evaluate_perp_step(
    *,
    signed_quantity: float,
    entry_price: float,
    bracket: PerpBracket | None,
    mark_price: float | None,
    prev_mark_price: float | None,
    liq_price: float | None,
    halted: bool,
    max_mark_gap_pct: float = 0.05,
) -> PerpStepDecision:
    """Deterministic per-tick risk evaluation (§9.5).

    Order of precedence: emergency halt > liquidation > mark/quote gap that
    jumps past a bracket > ordinary bracket exit > hold. A missing mark is a
    reconciliation trigger, never a fabricated value.
    """
    if halted:
        return PerpStepDecision("close", "emergency_halt", mark_price)
    if mark_price is None or mark_price <= 0:
        return PerpStepDecision("hold", "mark_unavailable_reconcile")

    # Liquidation first — it dominates every other exit.
    if liq_price is not None:
        if signed_quantity > 0 and mark_price <= liq_price:
            return PerpStepDecision("close", "liquidation", liq_price)
        if signed_quantity < 0 and mark_price >= liq_price:
            return PerpStepDecision("close", "liquidation", liq_price)

    # A large gap since the previous mark: fill brackets at the worse of the
    # bracket level and the new mark, not at an interpolated mid.
    gapped = (
        prev_mark_price is not None
        and prev_mark_price > 0
        and abs(mark_price - prev_mark_price) / prev_mark_price > max_mark_gap_pct
    )

    if bracket is not None:
        hit = bracket_exit(bracket, signed_quantity=signed_quantity, mark_price=mark_price)
        if hit == "stop_loss":
            # On a gap through the stop, the realistic fill is the current
            # mark (worse than the stop), not the stop level.
            fill = mark_price if gapped else bracket.stop_loss
            return PerpStepDecision("close", "stop_loss_gap" if gapped else "stop_loss", fill)
        if hit == "take_profit":
            fill = bracket.take_profit if not gapped else max(
                bracket.take_profit, mark_price
            ) if signed_quantity > 0 else min(bracket.take_profit, mark_price)
            return PerpStepDecision(
                "close", "take_profit_gap" if gapped else "take_profit", fill
            )

    return PerpStepDecision("hold", None)


@dataclass(frozen=True)
class PerpReconcileResult:
    reconciled: bool
    reason: str
    position_ids: tuple[int, ...]


class PerpPaperAdapter:
    """Small persistence-aware adapter around the pure perp calculations."""

    broker_name = "paper"

    def __init__(
        self,
        session: Session,
        *,
        paper_run_id: str,
        asset_id: str,
        market_ticker: str,
        multiplier: float,
        minimum_size: float,
        tick_size: float,
        fee_rate: float,
        collateral_usd: float = 0.0,
        max_leverage: float = DEFAULT_MAX_LEVERAGE,
        maintenance_margin_rate: float = 0.005,
    ) -> None:
        self.session = session
        self.paper_run_id = paper_run_id
        self.asset_id = asset_id
        self.market_ticker = market_ticker
        self.order = PerpOrder(0.0, tick_size, minimum_size, multiplier, fee_rate)
        self.multiplier = multiplier
        self.collateral_usd = collateral_usd
        self.max_leverage = max_leverage
        self.maintenance_margin_rate = maintenance_margin_rate

    def open(
        self,
        signed_quantity: float,
        quote: PerpQuote,
        *,
        decision_ts: int,
        bracket: PerpBracket | None = None,
        collateral_usd: float | None = None,
    ) -> PerpPaperPosition:
        order = PerpOrder(
            signed_quantity,
            self.order.tick_size,
            self.order.minimum_size,
            self.order.multiplier,
            self.order.fee_rate,
        )
        fill = fill_perp_order(order, quote, decision_ts=decision_ts)

        collateral = self.collateral_usd if collateral_usd is None else collateral_usd
        lev = check_entry_leverage(
            signed_quantity=fill.signed_quantity,
            multiplier=self.multiplier,
            price=fill.fill_price,
            collateral_usd=collateral,
            max_leverage=self.max_leverage,
        )
        if not lev.ok:
            raise PerpPaperError(lev.reason or "leverage_or_minimum_size")

        # A perp entry MUST carry a representable, directionally-valid bracket
        # (§9.5): reject before any simulated fill is recorded otherwise.
        if bracket is None:
            raise PerpPaperError("bracket_required")
        validate_bracket(
            bracket, entry_price=fill.fill_price, signed_quantity=fill.signed_quantity
        )

        liq = liquidation_price(
            signed_quantity=fill.signed_quantity,
            entry_price=fill.fill_price,
            multiplier=self.multiplier,
            collateral_usd=collateral,
            maintenance_margin_rate=self.maintenance_margin_rate,
        )

        position = PerpPaperPosition(
            paper_run_id=self.paper_run_id,
            asset_id=self.asset_id,
            market_ticker=self.market_ticker,
            signed_quantity=fill.signed_quantity,
            multiplier=self.multiplier,
            entry_price=fill.fill_price,
            entry_ts=fill.observed_at,
            fee_usd=fill.fee_usd,
        )
        self.session.add(position)
        self.session.flush()
        self.session.add(
            PerpPaperEvent(
                position_id=position.id,
                paper_run_id=self.paper_run_id,
                event_type="fill",
                observed_at=fill.observed_at,
                price=fill.fill_price,
                quantity=fill.signed_quantity,
                liquidation_price=liq,
                status="filled",
                quote_reference=fill.quote_reference,
                payload={
                    "bracket": {
                        "stop_loss": bracket.stop_loss,
                        "take_profit": bracket.take_profit,
                    },
                    "leverage": lev.leverage,
                    "collateral_usd": collateral,
                },
            )
        )
        return position

    # -- risk step + close (§9.5) -------------------------------------

    def step(
        self,
        position: PerpPaperPosition,
        *,
        mark_price: float | None,
        prev_mark_price: float | None,
        observed_at: int,
        quote_reference: dict[str, object],
        bracket: PerpBracket | None,
        collateral_usd: float | None = None,
        halted: bool = False,
    ) -> PerpStepDecision:
        """Evaluate one mark/quote tick and, if it implies an exit, close the
        position and persist the event. Returns the decision either way."""
        if position.status != "open":
            return PerpStepDecision("hold", "position_not_open")
        collateral = self.collateral_usd if collateral_usd is None else collateral_usd
        liq = liquidation_price(
            signed_quantity=position.signed_quantity,
            entry_price=position.entry_price,
            multiplier=position.multiplier,
            collateral_usd=collateral,
            maintenance_margin_rate=self.maintenance_margin_rate,
        )
        decision = evaluate_perp_step(
            signed_quantity=position.signed_quantity,
            entry_price=position.entry_price,
            bracket=bracket,
            mark_price=mark_price,
            prev_mark_price=prev_mark_price,
            liq_price=liq,
            halted=halted,
        )
        if decision.action == "close" and decision.exit_price:
            self.close(
                position,
                exit_price=decision.exit_price,
                reason=decision.reason or "risk_exit",
                observed_at=observed_at,
                quote_reference=quote_reference,
            )
        elif decision.reason == "mark_unavailable_reconcile":
            self.session.add(
                PerpPaperEvent(
                    position_id=position.id,
                    paper_run_id=self.paper_run_id,
                    event_type="reconciliation",
                    observed_at=observed_at,
                    status="reconciliation_required",
                    reason="mark_unavailable",
                    quote_reference=quote_reference,
                )
            )
        return decision

    def close(
        self,
        position: PerpPaperPosition,
        *,
        exit_price: float,
        reason: str,
        observed_at: int,
        quote_reference: dict[str, object],
    ) -> PerpCloseResult:
        result = close_perp_position(
            signed_quantity=position.signed_quantity,
            entry_price=position.entry_price,
            multiplier=position.multiplier,
            fee_rate=self.order.fee_rate,
            entry_fee_usd=position.fee_usd,
            funding_pnl_usd=position.funding_pnl_usd,
            exit_price=exit_price,
            reason=reason,
            quote_reference=quote_reference,
        )
        position.status = (
            "liquidated" if reason == "liquidation" else "closed"
        )
        position.realized_pnl_usd = result.realized_pnl_usd
        position.fee_usd = result.fees_usd
        self.session.add(position)
        self.session.add(
            PerpPaperEvent(
                position_id=position.id,
                paper_run_id=self.paper_run_id,
                event_type="liquidation" if reason == "liquidation" else "exit_fill",
                observed_at=observed_at,
                price=exit_price,
                quantity=-position.signed_quantity,
                status="closed",
                reason=reason,
                quote_reference=quote_reference,
                payload={
                    "realized_pnl_usd": result.realized_pnl_usd,
                    "funding_pnl_usd": result.funding_pnl_usd,
                    "fees_usd": result.fees_usd,
                },
            )
        )
        return result

    # -- restart reconciliation (§9.7) ------------------------------

    def open_positions(self) -> list[PerpPaperPosition]:
        return list(
            self.session.execute(
                select(PerpPaperPosition).where(
                    PerpPaperPosition.paper_run_id == self.paper_run_id,
                    PerpPaperPosition.asset_id == self.asset_id,
                    PerpPaperPosition.status == "open",
                )
            ).scalars()
        )

    def reconcile_open_positions(
        self, *, fresh_mark: float | None, mark_observed_at: int | None, now_ts: int
    ) -> PerpReconcileResult:
        """Before any new perp entry: every open position for this asset must
        have a fresh mark. A missing/stale mark blocks all new entries and
        records a reconciliation event per position (§9.7)."""
        positions = self.open_positions()
        if not positions:
            return PerpReconcileResult(True, "no_open_positions", ())
        stale = fresh_mark is None or fresh_mark <= 0 or mark_observed_at is None
        if not stale and now_ts - int(mark_observed_at) > 120:
            stale = True
        if stale:
            for p in positions:
                self.session.add(
                    PerpPaperEvent(
                        position_id=p.id,
                        paper_run_id=self.paper_run_id,
                        event_type="reconciliation",
                        observed_at=now_ts,
                        status="reconciliation_required",
                        reason="no_fresh_mark_on_restart",
                    )
                )
            return PerpReconcileResult(
                False, "no_fresh_mark_on_restart", tuple(p.id for p in positions)
            )
        for p in positions:
            self.session.add(
                PerpPaperEvent(
                    position_id=p.id,
                    paper_run_id=self.paper_run_id,
                    event_type="reconciliation",
                    observed_at=now_ts,
                    price=fresh_mark,
                    status="reconciled",
                )
            )
        return PerpReconcileResult(True, "reconciled", tuple(p.id for p in positions))

    def record_mark(
        self,
        position: PerpPaperPosition,
        *,
        mark_price: float,
        observed_at: int,
        quote_reference: dict[str, object],
    ) -> PerpMarkToMarket:
        state = PerpAccountState(
            0.0,
            position.signed_quantity,
            position.entry_price,
            position.multiplier,
            fees_usd=position.fee_usd,
            funding_pnl_usd=position.funding_pnl_usd,
        )
        result = mark_to_market(state, mark_price=mark_price)
        self.session.add(
            PerpPaperEvent(
                position_id=position.id,
                paper_run_id=self.paper_run_id,
                event_type="mark",
                observed_at=observed_at,
                price=mark_price,
                status="observed",
                quote_reference=quote_reference,
            )
        )
        return result


__all__ = [
    "ABSOLUTE_MAX_LEVERAGE",
    "DEFAULT_MAX_LEVERAGE",
    "LeverageCheck",
    "PerpAccountState",
    "PerpBracket",
    "PerpCloseResult",
    "PerpMarkToMarket",
    "PerpOrder",
    "PerpPaperAdapter",
    "PerpPaperError",
    "PerpPaperFill",
    "PerpQuote",
    "PerpReconcileResult",
    "PerpStepDecision",
    "bracket_exit",
    "check_entry_leverage",
    "close_perp_position",
    "evaluate_perp_step",
    "fill_perp_order",
    "liquidation_price",
    "mark_to_market",
    "realized_funding",
    "validate_bracket",
]
