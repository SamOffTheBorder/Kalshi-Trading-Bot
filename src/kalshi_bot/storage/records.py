"""Persistence helpers bridging strategy types to the schema of record."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from kalshi_bot.storage.models import SignalRecord
from kalshi_bot.strategy.base import Decision, StrategyContext


def record_signal(
    session: Session,
    decision: Decision,
    context: StrategyContext,
    *,
    mode: str,
    backtest_run_id: int | None = None,
) -> SignalRecord:
    """Persist one evaluation — HOLD or not — with its full inputs.

    The calling loop (backtest/paper/live) invokes this for EVERY decision;
    that's the audit-trail requirement, not an optional nicety.
    """
    row = SignalRecord(
        evaluated_at_ts=context.now_ts,
        mode=mode,
        backtest_run_id=backtest_run_id,
        strategy_name=decision.strategy_name,
        market_ticker=decision.market_ticker,
        action=decision.action.value,
        market_yes_price=context.yes_ask_cents,
        bs_probability=decision.bs_probability,
        mc_probability=decision.mc_probability,
        raw_edge=decision.raw_edge,
        fee_adjusted_edge=decision.fee_adjusted_edge,
        confidence=decision.confidence,
        hold_reason=decision.hold_reason,
        context=json.dumps(
            {
                "spot": context.spot,
                "vol_annual": context.vol_annual,
                "vol_source": context.vol_source,
                "strike_type": context.strike_type,
                "floor_strike": context.floor_strike,
                "cap_strike": context.cap_strike,
                "yes_bid_cents": context.yes_bid_cents,
                "yes_ask_cents": context.yes_ask_cents,
                "minutes_to_expiry": context.minutes_to_expiry,
                "extras": context.extras,
            }
        ),
    )
    session.add(row)
    return row
