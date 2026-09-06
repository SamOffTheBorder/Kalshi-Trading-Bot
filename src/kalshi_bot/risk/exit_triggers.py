"""Mandatory server-side brackets for perps positions (tasks.md 5.2, design D4).

**Invariant: no perps position exists without a server-side stop-loss.**
Rationale (design.md D4): this bot's own operational history includes four
silent process deaths. In-process stop logic — a Python object watching
price and deciding when to exit — would have left leveraged positions
unmanaged during each one. A bracket attached via Kalshi's exit-trigger
endpoints (tasks.md 4.5, `KalshiMarginClient.set_isolated_exit_trigger` /
`set_cross_exit_trigger`) lives on the exchange, not in this process: it
fires even if the bot is dead (spec: perps-trading, "Bot process dies with
position open").

Consequence: bracket attachment happens **in the same logical operation as
entry**, before the caller is allowed to treat the position as open. If
attachment fails for any reason, this module submits a closing order for
the just-opened position immediately and reports the incident — it does not
retry the bracket and it does not leave the position open unprotected while
someone investigates (spec: perps-trading, "Bracket attachment fails").

Event contracts are explicitly out of scope here (design.md D4): they have a
defined max loss (the entry cost) so a bracket is optional there, not
mandatory. This module is perps-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from loguru import logger

from kalshi_bot.execution.kalshi_margin_client import KalshiMarginClient

PositionKind = Literal["isolated", "cross"]


@dataclass(frozen=True)
class BracketResult:
    """Outcome of `attach_mandatory_bracket`. `ok=False` always means the
    position has already been closed by this call — callers must never
    treat the position as open when `ok` is False."""

    ok: bool
    exit_trigger: dict[str, object] | None = None
    closed_due_to_failure: bool = False
    error: str | None = None


def attach_mandatory_bracket(
    client: KalshiMarginClient,
    *,
    ticker: str,
    position_kind: PositionKind,
    stop_loss_price: str,
    take_profit_price: str | None = None,
    close_side: Literal["bid", "ask"],
    close_count: str,
    marketable_close_price: str,
) -> BracketResult:
    """Attach a stop-loss (and optional take-profit) bracket to a perps
    position that was just opened. On any failure, immediately submits a
    closing order for `close_count` units on `close_side` and returns
    `ok=False, closed_due_to_failure=True` — the caller MUST treat the
    position as closed, not "open without a bracket," in that case.

    `close_side`/`close_count` describe the order that flattens the position
    (the opposite side from entry, same size) — passed in rather than
    inferred, since this module has no independent view of the position;
    the caller (which just placed the entry) does.

    `marketable_close_price` must be a price guaranteed to cross the spread
    on `close_side` (e.g. well past the current best bid/ask) — the caller
    supplies it because perps prices are real, unbounded dollar amounts
    (unlike event contracts' [0,1]-style pricing), so no fixed constant here
    could be marketable across every instrument this is ever called for.
    """
    set_trigger = (
        client.set_isolated_exit_trigger
        if position_kind == "isolated"
        else client.set_cross_exit_trigger
    )
    try:
        exit_trigger = set_trigger(
            ticker, stop_loss_price=stop_loss_price, take_profit_price=take_profit_price
        )
    except Exception as exc:  # any failure here must trigger the close path, deliberately broad
        logger.error(
            "attach_mandatory_bracket: FAILED to attach bracket for {} ({}) — "
            "closing the position immediately per the no-unbracketed-position invariant: {}",
            ticker,
            position_kind,
            exc,
        )
        return _close_after_failed_bracket(
            client,
            ticker=ticker,
            close_side=close_side,
            close_count=close_count,
            marketable_close_price=marketable_close_price,
            error=str(exc),
        )
    logger.info(
        "attach_mandatory_bracket: bracket attached for {} ({}), stop={}, target={}",
        ticker,
        position_kind,
        stop_loss_price,
        take_profit_price,
    )
    return BracketResult(ok=True, exit_trigger=exit_trigger)


def _close_after_failed_bracket(
    client: KalshiMarginClient,
    *,
    ticker: str,
    close_side: Literal["bid", "ask"],
    close_count: str,
    marketable_close_price: str,
    error: str,
) -> BracketResult:
    try:
        client.create_order(
            market_ticker=ticker,
            side=close_side,
            count=close_count,
            # Cross the spread to guarantee the close actually fills — this is
            # the one place in the codebase where paying the taker fee is
            # correct: an unbracketed leveraged position is worse than a fee.
            price=marketable_close_price,
            time_in_force="immediate_or_cancel",
            post_only=False,
            reduce_only=True,
        )
    except Exception as close_exc:  # deliberately broad — nothing left to fall back to
        logger.critical(
            "attach_mandatory_bracket: bracket attach AND closing order both failed for {} "
            "— position may still be open and UNPROTECTED. Manual intervention required. "
            "bracket_error={!r} close_error={!r}",
            ticker,
            error,
            close_exc,
        )
        return BracketResult(
            ok=False,
            closed_due_to_failure=False,
            error=f"bracket_error={error!r} close_error={close_exc!r}",
        )
    return BracketResult(ok=False, closed_due_to_failure=True, error=error)


__all__ = ["BracketResult", "PositionKind", "attach_mandatory_bracket"]
