"""Narrow sports binary paper adapter behind the shared orchestrator
(multi-venue-paper-trading §10.5/§10.6).

This reuses ONLY the safe binary fill/settlement mechanics (`PaperBroker`:
marketable limit protection, side-aware worst-of-quote, documented taker fee,
official Kalshi settlement, restart recovery from `SimulatedTrade` rows). It
adds a sports-specific admission wall in front of every entry:

1. a completed, exactly-matching `research_promising` feasibility report
   (`evaluate_sports_paper_admission`), unchanged candidate identity, and an
   operator acknowledgement — no report, no fills;
2. conservative market classification (`classify_market`) — pre-game,
   single-game, two-outcome only; futures / player props / parlays / combos /
   multi-outcome / unknown-rules / non-sports / not-currently-tradeable and
   in-play are all rejected before strategy execution;
3. causal evidence freshness — required evidence must be eligible at the
   decision timestamp and not conflicted without a resolution rule;
4. an explicit `copy_trading_unsupported` rejection for any decision attributed
   to another trader / account.

Settlement uses the official Kalshi result only; a third-party score is never
substituted. Restart reconciliation settles resolved open positions and
blocks new entries while any position is unresolved.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.config.lifecycle import Domain
from kalshi_bot.data.sports.classifier import Classification, classify_market
from kalshi_bot.data.sports.evidence import EvidenceCard, eligible_cards, resolve_conflicts
from kalshi_bot.data.sports.validation import SportsAdmission
from kalshi_bot.execution.broker_protocol import MarketSnapshot, OrderRequest
from kalshi_bot.execution.orchestrator import AdapterDecision, ReconciliationOutcome
from kalshi_bot.execution.paper_broker import PaperBroker
from kalshi_bot.storage.models import KalshiMarket, SimulatedTrade

SPORTS_SERIES_PREFIX = "KXSPORT"  # only used as a last-resort ticker->asset tag


@dataclass(frozen=True)
class SportsCandidate:
    """Immutable identity of the approved pilot candidate."""

    sport: str
    market_class: str  # e.g. "pre_game_moneyline"
    strategy_version: str
    execution_assumptions_hash: str

    def matches(self, other: SportsCandidate) -> bool:
        return (
            self.sport == other.sport
            and self.market_class == other.market_class
            and self.strategy_version == other.strategy_version
            and self.execution_assumptions_hash == other.execution_assumptions_hash
        )


@dataclass(frozen=True)
class SportsMarketState:
    """One point-in-time listed sports market for a candidate."""

    market_ticker: str
    series_ticker: str
    raw_market: dict[str, object]
    raw_series: dict[str, object]
    observed_at: int
    close_ts: int
    event_start_ts: int
    in_play: bool
    yes_bid_cents: int | None
    yes_ask_cents: int | None
    result: str | None = None


@dataclass(frozen=True)
class SportsSignal:
    action: str  # "hold" | "buy"
    side: str | None = None  # "yes" | "no"
    limit_price_cents: int | None = None
    quantity: int = 1
    reason: str | None = None
    attributed_to_other_trader: bool = False
    meta: dict[str, object] = field(default_factory=dict)


SportsStrategyFn = Callable[[SportsMarketState], SportsSignal]


def hold_sports_strategy(_state: SportsMarketState) -> SportsSignal:
    return SportsSignal(action="hold", reason="no_strategy_configured")


@dataclass
class SportsPaperAdapter:
    """Shared-envelope wrapper over `PaperBroker` for a sports pilot run."""

    session: Session
    candidate: SportsCandidate
    admission: SportsAdmission
    market_source: Callable[[int], SportsMarketState | None]
    evidence_source: Callable[[str, int], Sequence[EvidenceCard]]
    settlement_source: Callable[[str], str | None]
    starting_cash_usd: float
    strategy: SportsStrategyFn = hold_sports_strategy
    required_claims: tuple[str, ...] = ()
    conflict_resolution_priority: tuple[str, ...] = ()
    max_data_age_seconds: int = 300

    domain: Domain = "sports"
    broker_name: str = "paper"

    _broker: PaperBroker = field(init=False)
    _open_ticker: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._broker = PaperBroker(self.session, starting_cash_usd=self.starting_cash_usd)
        tickers = self._broker.open_position_tickers()
        self._open_ticker = tickers[0] if tickers else None

    # -- DomainPaperAdapter -----------------------------------------

    def reconcile(self, asset_id: str) -> ReconciliationOutcome:
        rows = list(
            self.session.execute(
                select(SimulatedTrade).where(
                    SimulatedTrade.mode == "paper",
                    SimulatedTrade.status == "open",
                )
            ).scalars()
        )
        if not rows:
            return ReconciliationOutcome(asset_id, True, "no_open_positions")
        unresolved: list[str] = []
        settled: list[str] = []
        for row in rows:
            result = self.settlement_source(row.market_ticker)
            if result in ("yes", "no"):
                net = self._broker.settle_market(row.market_ticker, result, row.entry_ts)
                self.session.commit()
                settled.append(f"{row.market_ticker}:{result}:{net:.2f}")
                if self._open_ticker == row.market_ticker:
                    self._open_ticker = None
            else:
                unresolved.append(row.market_ticker)
        if unresolved:
            return ReconciliationOutcome(
                asset_id, False, "open_position_without_official_result",
                {"unresolved": unresolved, "settled": settled},
            )
        return ReconciliationOutcome(asset_id, True, "reconciled", {"settled": settled})

    def evaluate(self, asset_id: str, *, now_ts: int, may_fill: bool) -> AdapterDecision:
        # 0. Admission wall — a non-promising / unacknowledged report never fills.
        if not self.admission.admitted:
            return self._blocked(asset_id, "admission_blocked", self.admission.reason)

        state = self.market_source(now_ts)
        if state is None:
            return AdapterDecision(
                asset_id, self.domain, "no_market", "no_listed_market",
                reason="discovery_found_no_pilot_market",
            )

        # 1. In-play / shape / rules classification.
        if state.in_play or now_ts >= state.event_start_ts:
            return self._blocked(asset_id, "in_play_rejected", "market_in_play", state)
        classification = classify_market(state.raw_market, series=state.raw_series)
        if not classification.eligible:
            return self._blocked(
                asset_id, "classification_rejected",
                classification.reason or "unclassified_market", state,
            )
        if classification.outcome_shape != "binary":
            return self._blocked(
                asset_id, "classification_rejected", "non_binary_shape", state
            )

        # 2. Freshness.
        if now_ts - state.observed_at > self.max_data_age_seconds:
            return self._blocked(
                asset_id, "stale_quote", f"quote_age_{now_ts - state.observed_at}s", state
            )

        # 3. Required evidence must be causal + not unresolved-conflicted.
        ev_status = self._evidence_status(state.market_ticker, now_ts)
        if ev_status is not None:
            return self._blocked(asset_id, "evidence_blocked", ev_status, state)

        # 4. Strategy.
        signal = self.strategy(state)
        payload = self._payload(state, classification, signal.meta)
        if signal.attributed_to_other_trader:
            return self._blocked(
                asset_id, "copy_trading_unsupported", "attributed_to_other_trader",
                state, payload,
            )
        if signal.action != "buy":
            return AdapterDecision(
                asset_id, self.domain, "hold", "hold",
                reason=signal.reason or "strategy_hold", payload=payload,
            )
        if self._open_ticker is not None:
            return AdapterDecision(
                asset_id, self.domain, "blocked", "position_already_open",
                reason="one_position_per_pilot", payload=payload,
            )
        if signal.side not in ("yes", "no") or signal.limit_price_cents is None:
            return AdapterDecision(
                asset_id, self.domain, "blocked", "invalid_signal",
                reason="buy_needs_side_and_limit", payload=payload,
            )

        would_fill = self._would_fill(state, signal.side, signal.limit_price_cents)
        payload["would_fill_price_cents"] = would_fill
        if would_fill is None:
            return AdapterDecision(
                asset_id, self.domain, "blocked", "no_fillable_quote",
                reason="required_quote_side_absent", payload=payload,
            )

        if not may_fill:
            return AdapterDecision(
                asset_id, self.domain, "entry", "shadow_would_fill",
                reason="shadow_mode_no_paper_fill", would_fill=True, payload=payload,
            )

        self._broker.set_current_quote(
            MarketSnapshot(
                market_ticker=state.market_ticker,
                ts=state.observed_at,
                yes_bid_cents=state.yes_bid_cents,
                yes_ask_cents=state.yes_ask_cents,
            )
        )
        result = asyncio.run(
            self._broker.place_order(
                OrderRequest(
                    market_ticker=state.market_ticker,
                    side=signal.side,  # type: ignore[arg-type]
                    quantity=max(1, int(signal.quantity)),
                    limit_price_cents=signal.limit_price_cents,
                )
            )
        )
        self.session.commit()
        if result.status == "filled":
            self._open_ticker = state.market_ticker
            return AdapterDecision(
                asset_id, self.domain, "entry", "filled", would_fill=True, filled=True,
                payload={
                    **payload,
                    "fill_price_cents": result.fill_price_cents,
                    "quantity": result.quantity,
                    "order_id": result.order_id,
                },
            )
        return AdapterDecision(
            asset_id, self.domain, "blocked", "order_rejected",
            reason=result.reject_reason, payload=payload,
        )

    # -- helpers --------------------------------------------------

    def _evidence_status(self, market_ticker: str, now_ts: int) -> str | None:
        if not self.required_claims:
            return None
        cards = list(self.evidence_source(market_ticker, now_ts))
        eligible = eligible_cards(cards, decision_ts=now_ts)
        grouped = resolve_conflicts(cards, decision_ts=now_ts)
        for claim in self.required_claims:
            claim_cards = grouped.get(claim, [])
            if not claim_cards:
                return f"missing_causal_evidence:{claim}"
            values = {c.claim + "|" + c.raw_content_hash for c in claim_cards}
            if len(values) > 1 and not any(
                c.provider in self.conflict_resolution_priority for c in claim_cards
            ):
                return f"evidence_conflicted:{claim}"
        _ = eligible
        return None

    @staticmethod
    def _would_fill(state: SportsMarketState, side: str, limit_cents: int) -> int | None:
        if side == "yes":
            price = state.yes_ask_cents
        else:
            price = None if state.yes_bid_cents is None else 100 - state.yes_bid_cents
        if price is None or not 1 <= price <= 99:
            return None
        return price if price <= limit_cents else None

    def _payload(
        self, state: SportsMarketState, classification: Classification, meta: dict
    ) -> dict[str, object]:
        return {
            "market_ticker": state.market_ticker,
            "series_ticker": state.series_ticker,
            "sport": classification.sport,
            "settlement_source": classification.settlement_source,
            "candidate": {
                "sport": self.candidate.sport,
                "market_class": self.candidate.market_class,
                "strategy_version": self.candidate.strategy_version,
                "execution_assumptions_hash": self.candidate.execution_assumptions_hash,
            },
            "report_outcome": self.admission.report_outcome,
            "yes_bid_cents": state.yes_bid_cents,
            "yes_ask_cents": state.yes_ask_cents,
            **meta,
        }

    def _blocked(
        self,
        asset_id: str,
        status: str,
        reason: str,
        state: SportsMarketState | None = None,
        payload: dict[str, object] | None = None,
    ) -> AdapterDecision:
        pl = payload or {}
        if state is not None and "market_ticker" not in pl:
            pl = {**pl, "market_ticker": state.market_ticker}
        return AdapterDecision(
            asset_id, self.domain, "blocked", status, reason=reason, payload=pl
        )


def db_sports_settlement_source(session: Session) -> Callable[[str], str | None]:
    """Official Kalshi result lookup by market ticker (never a third-party score)."""

    def _source(market_ticker: str) -> str | None:
        row = session.execute(
            select(KalshiMarket.result).where(KalshiMarket.ticker == market_ticker)
        ).scalar_one_or_none()
        if not row:
            return None
        return row.lower() if row.lower() in ("yes", "no") else None

    return _source


__all__ = [
    "SportsCandidate",
    "SportsMarketState",
    "SportsPaperAdapter",
    "SportsSignal",
    "SportsStrategyFn",
    "db_sports_settlement_source",
    "hold_sports_strategy",
]
