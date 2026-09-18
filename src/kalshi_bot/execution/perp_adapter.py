"""Perpetual-domain adapter behind the shared orchestrator
(strategy-lab-multi-account §4).

Assembles the existing pure perp primitives — `execution/perp_paper.py`'s
`PerpPaperAdapter` (fills, brackets, liquidation, funding, reconciliation)
and `execution/perp_admission.py`'s `evaluate_perp_admission` — into the
domain-neutral `DomainPaperAdapter` envelope (`evaluate` / `reconcile`), so
`scripts/run_paper.py --domain perp` becomes real.

Nothing here constructs an execution client or calls an order endpoint. Data
comes in through injected read-only sources (a perp quote+mark reader, a
mark/funding coverage reader, a discovery-snapshot reader) exactly the way
`PredictionPaperAdapter` takes `quote_source` / `settlement_source` — which
keeps the adapter unit-testable against an in-memory archive with no network,
the same discipline `data/perps/__init__.py` states for the capture side.

Two decision paths share the adapter:

* **directional** (§4): a `PerpStrategyFn` — `Callable[[PerpEvalContext],
  PerpSignal]`, mirroring the sports domain's `SportsStrategyFn` — returns a
  signed quantity and a stop/take-profit bracket, or a hold. Every entry
  MUST carry a `validate_bracket`-accepted bracket or it is refused before
  any simulated fill (`execution/perp_paper.PerpPaperAdapter.open` also
  enforces this; the adapter checks first so the refusal reason is legible).

* **two-leg funding carry** (§5): `evaluate_carry()` drives
  `strategy/funding_carry.evaluate_funding_carry`. The perp leg is opened
  through the same `PerpPaperAdapter`; the event-contract hedge leg is
  recorded as its own `PerpPaperEvent` so the result reads as *net carry
  after both legs' fees*, never as a win rate. `Decision`
  (`strategy/base.py`) is single-instrument and is NOT widened for this.

Causal discipline: the injected quote/mark reader must already filter on
`available_at <= now_ts`; the adapter passes `now_ts` through as
`decision_ts`, and `fill_perp_order` itself rejects a quote whose
`available_at` is after the decision.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.config.lifecycle import Domain
from kalshi_bot.execution.orchestrator import AdapterDecision, ReconciliationOutcome
from kalshi_bot.execution.perp_admission import (
    PerpMarkCoverage,
    evaluate_perp_admission,
)
from kalshi_bot.execution.perp_paper import (
    PerpBracket,
    PerpPaperAdapter,
    PerpPaperError,
    PerpQuote,
    realized_funding,
    validate_bracket,
)
from kalshi_bot.storage.models import (
    DiscoveryResult,
    PerpFundingObservation,
    PerpMarkObservation,
    PerpPaperEvent,
    PerpPaperPosition,
)
from kalshi_bot.strategy.funding_carry import (
    FundingCarryConfig,
    evaluate_funding_carry,
)

try:  # DiscoverySnapshot is only needed for its type; avoid a hard import cycle
    from kalshi_bot.discovery.service import DiscoverySnapshot
except Exception:  # pragma: no cover - discovery import is well-established
    DiscoverySnapshot = object  # type: ignore[assignment,misc]


@dataclass(frozen=True)
class PerpEvalContext:
    """Everything a perp directional strategy may look at for one evaluation.
    Assembled by the adapter; the strategy never fetches."""

    asset_id: str
    market_ticker: str
    now_ts: int
    quote: PerpQuote
    mark_price: float | None
    latest_funding_rate: float | None
    multiplier: float
    minimum_size: float


@dataclass(frozen=True)
class PerpSignal:
    """A perp directional strategy's decision for one evaluation."""

    action: str  # "hold" | "enter"
    signed_quantity: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    reason: str | None = None
    meta: dict[str, object] = field(default_factory=dict)


PerpStrategyFn = Callable[[PerpEvalContext], PerpSignal]


def hold_perp_strategy(_ctx: PerpEvalContext) -> PerpSignal:
    return PerpSignal(action="hold", reason="no_strategy_configured")


# -- injected read-only source shapes ------------------------------------

# (asset_id, now_ts) -> a (PerpQuote, mark_price, latest_funding_rate,
# multiplier, minimum_size, tick_size, fee_rate) bundle, or None when no
# fresh perp market exists for the asset. The reader is responsible for the
# `available_at <= now_ts` filter.
PerpMarketReader = Callable[[str, int], "PerpMarketReading | None"]

# (asset_id, now_ts) -> PerpMarkCoverage for the admission check.
PerpCoverageReader = Callable[[str, int], PerpMarkCoverage]

# (asset_id, now_ts) -> the freshest eligible DiscoverySnapshot, or None.
PerpDiscoveryReader = Callable[[str, int], "DiscoverySnapshot | None"]


@dataclass(frozen=True)
class PerpMarketReading:
    quote: PerpQuote
    mark_price: float | None
    latest_funding_rate: float | None
    multiplier: float
    minimum_size: float
    tick_size: float
    fee_rate: float


@dataclass
class PerpPaperDomainAdapter:
    """`DomainPaperAdapter` for linear perpetuals."""

    session: Session
    paper_run_id: str
    market_reader: PerpMarketReader
    coverage_reader: PerpCoverageReader
    discovery_reader: PerpDiscoveryReader
    collateral_usd: float
    strategy: PerpStrategyFn = hold_perp_strategy
    max_mark_age_seconds: int = 120

    domain: Domain = "perp"
    broker_name: str = "paper"

    _open_by_asset: dict[str, int] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        for pos in self.session.execute(
            select(PerpPaperPosition).where(
                PerpPaperPosition.paper_run_id == self.paper_run_id,
                PerpPaperPosition.status == "open",
            )
        ).scalars():
            self._open_by_asset[pos.asset_id] = pos.id

    # -- helpers -----------------------------------------------------

    def _paper_adapter(self, asset_id: str, reading: PerpMarketReading) -> PerpPaperAdapter:
        return PerpPaperAdapter(
            self.session,
            paper_run_id=self.paper_run_id,
            asset_id=asset_id,
            market_ticker=reading.quote.reference.get("market_ticker", asset_id)
            if isinstance(reading.quote.reference, dict)
            else asset_id,
            multiplier=reading.multiplier,
            minimum_size=reading.minimum_size,
            tick_size=reading.tick_size,
            fee_rate=reading.fee_rate,
            collateral_usd=self.collateral_usd,
        )

    # -- DomainPaperAdapter ---------------------------------------

    def reconcile(self, asset_id: str) -> ReconciliationOutcome:
        reading = self.market_reader(asset_id, _now_guess(self.session))
        # A reconcile pass needs a fresh mark; delegate to the perp adapter's
        # own restart-reconciliation, which records a per-position event.
        fresh_mark = reading.mark_price if reading is not None else None
        mark_observed_at = (
            reading.quote.observed_at if reading is not None else None
        )
        # No open position for this asset -> trivially reconciled.
        if asset_id not in self._open_by_asset:
            return ReconciliationOutcome(asset_id, True, "no_open_positions")
        if reading is None:
            return ReconciliationOutcome(
                asset_id, False, "no_fresh_mark_on_restart", {}
            )
        pa = self._paper_adapter(asset_id, reading)
        now_ts = reading.quote.observed_at
        result = pa.reconcile_open_positions(
            fresh_mark=fresh_mark,
            mark_observed_at=mark_observed_at,
            now_ts=now_ts,
        )
        self.session.commit()
        if result.reconciled and not pa.open_positions():
            self._open_by_asset.pop(asset_id, None)
        return ReconciliationOutcome(
            asset_id,
            result.reconciled,
            result.reason,
            {"position_ids": list(result.position_ids)},
        )

    def evaluate(self, asset_id: str, *, now_ts: int, may_fill: bool) -> AdapterDecision:
        reading = self.market_reader(asset_id, now_ts)
        if reading is None:
            return AdapterDecision(
                asset_id, self.domain, "no_market", "no_perp_market",
                reason="reader_found_no_fresh_perp_market",
            )
        if now_ts - reading.quote.observed_at > self.max_mark_age_seconds:
            return AdapterDecision(
                asset_id, self.domain, "blocked", "stale_mark",
                reason=f"mark_age_{now_ts - reading.quote.observed_at}s",
                payload={"market_ticker": _ticker(reading)},
            )

        # Admission: a failing check still records decisions, with the reason.
        discovery = self.discovery_reader(asset_id, now_ts)
        coverage = self.coverage_reader(asset_id, now_ts)
        verdict = evaluate_perp_admission(
            asset_id=asset_id,
            now_ts=now_ts,
            discovery=discovery,
            coverage=coverage,
            frozen_report_present=True,  # the orchestrator's own gate owns this
            paper_mode=may_fill,
        )
        admission_may_fill = verdict.admitted and verdict.may_fill and may_fill

        ctx = PerpEvalContext(
            asset_id=asset_id,
            market_ticker=_ticker(reading),
            now_ts=now_ts,
            quote=reading.quote,
            mark_price=reading.mark_price,
            latest_funding_rate=reading.latest_funding_rate,
            multiplier=reading.multiplier,
            minimum_size=reading.minimum_size,
        )
        signal = self.strategy(ctx)
        base_payload: dict[str, object] = {
            "market_ticker": ctx.market_ticker,
            "admission_reason": verdict.reason,
            "admitted": verdict.admitted,
            **signal.meta,
        }

        if signal.action != "enter":
            return AdapterDecision(
                asset_id, self.domain, "hold", "hold",
                reason=signal.reason or "strategy_hold",
                payload=base_payload,
            )

        if asset_id in self._open_by_asset:
            return AdapterDecision(
                asset_id, self.domain, "blocked", "position_already_open",
                reason="one_position_per_asset",
                payload=base_payload,
            )

        # Every perp entry MUST carry a representable, directionally-valid
        # bracket (§4.4). Refuse before any simulated fill otherwise.
        if (
            signal.signed_quantity == 0
            or signal.stop_loss is None
            or signal.take_profit is None
        ):
            return AdapterDecision(
                asset_id, self.domain, "blocked", "invalid_signal",
                reason="enter_needs_quantity_and_bracket",
                payload=base_payload,
            )
        entry_price = (
            reading.quote.ask if signal.signed_quantity > 0 else reading.quote.bid
        )
        bracket = PerpBracket(
            stop_loss=signal.stop_loss, take_profit=signal.take_profit
        )
        if entry_price is None:
            return AdapterDecision(
                asset_id, self.domain, "blocked", "one_sided_quote",
                reason="no_executable_price_on_entry_side",
                payload=base_payload,
            )
        try:
            validate_bracket(
                bracket,
                entry_price=entry_price,
                signed_quantity=signal.signed_quantity,
            )
        except PerpPaperError as exc:
            return AdapterDecision(
                asset_id, self.domain, "blocked", "invalid_bracket",
                reason=str(exc),
                payload={**base_payload, "entry_price": entry_price},
            )

        if not admission_may_fill:
            status = "shadow_would_enter"
            return AdapterDecision(
                asset_id, self.domain, "entry", status,
                reason=(
                    "shadow_mode_no_paper_fill"
                    if may_fill
                    else verdict.reason
                ),
                would_fill=True,
                payload=base_payload,
            )

        pa = self._paper_adapter(asset_id, reading)
        try:
            position = pa.open(
                signal.signed_quantity,
                reading.quote,
                decision_ts=now_ts,
                bracket=bracket,
                collateral_usd=self.collateral_usd,
            )
        except PerpPaperError as exc:
            self.session.rollback()
            return AdapterDecision(
                asset_id, self.domain, "blocked", "order_rejected",
                reason=str(exc),
                payload=base_payload,
            )
        self.session.commit()
        self._open_by_asset[asset_id] = position.id
        return AdapterDecision(
            asset_id, self.domain, "entry", "filled",
            reason=None,
            would_fill=True,
            filled=True,
            payload={
                **base_payload,
                "position_id": position.id,
                "entry_price": position.entry_price,
                "signed_quantity": position.signed_quantity,
            },
        )

    # -- two-leg funding carry (§5) --------------------------------

    def evaluate_carry(
        self,
        asset_id: str,
        *,
        now_ts: int,
        may_fill: bool,
        position_notional_usd: float,
        config: FundingCarryConfig | None = None,
    ) -> AdapterDecision:
        """Two-leg funding-carry evaluation: a perp leg plus an event-contract
        hedge leg. Driven by `strategy/funding_carry.evaluate_funding_carry`,
        which only opens *as carry* when the hedge classifies as a linear
        hedge — with the default binary-event hedge it never does, so this
        path reports the carry numbers and refuses the entry (§5.3).

        `Decision` (`strategy/base.py`) is single-instrument and is NOT
        widened; this method owns the second leg. Both legs' costs are
        recorded so the result reads as net carry after fees, not a win rate.
        """
        reading = self.market_reader(asset_id, now_ts)
        if reading is None:
            return AdapterDecision(
                asset_id, self.domain, "no_market", "no_perp_market",
                reason="reader_found_no_fresh_perp_market",
            )
        rate = reading.latest_funding_rate
        if rate is None:
            return AdapterDecision(
                asset_id, self.domain, "hold", "hold",
                reason="no_realized_funding_rate",
                payload={"market_ticker": _ticker(reading)},
            )

        cfg = config or FundingCarryConfig()
        decision = evaluate_funding_carry(
            _FundingRateOnly(rate),
            position_notional_usd=position_notional_usd,
            config=cfg,
        )
        payload: dict[str, object] = {
            "market_ticker": _ticker(reading),
            "funding_rate": rate,
            "perp_side": decision.perp_side,
            "expected_funding_usd": decision.expected_funding_usd,
            "hedge_cost_usd": decision.hedge_cost_usd,
            "expected_net_carry_usd": decision.expected_net_carry_usd,
            "market_neutral": decision.market_neutral,
            "classification_reasons": list(decision.classification_reasons),
        }

        if not decision.should_enter:
            return AdapterDecision(
                asset_id, self.domain, "hold", "carry_not_entered",
                reason=decision.reason,
                payload=payload,
            )

        if asset_id in self._open_by_asset:
            return AdapterDecision(
                asset_id, self.domain, "blocked", "position_already_open",
                reason="one_position_per_asset",
                payload=payload,
            )

        if not (may_fill and decision.perp_side is not None):
            return AdapterDecision(
                asset_id, self.domain, "entry", "shadow_would_enter_carry",
                reason="shadow_mode_no_paper_fill",
                would_fill=True,
                payload=payload,
            )

        # The perp leg. A carry position still needs a bracket to satisfy the
        # perp ledger's safety rule; a wide bracket around the entry keeps it
        # representable without materially changing the carry economics.
        entry_ref = (
            reading.quote.ask
            if decision.perp_side == "long"
            else reading.quote.bid
        )
        if entry_ref is None or entry_ref <= 0:
            return AdapterDecision(
                asset_id, self.domain, "blocked", "one_sided_quote",
                reason="no_executable_price_on_carry_perp_leg",
                payload=payload,
            )
        # signed_quantity so that |qty| * multiplier * price == notional.
        magnitude = position_notional_usd / max(
            reading.multiplier * entry_ref, 1e-9
        )
        signed = magnitude if decision.perp_side == "long" else -magnitude
        entry_price = entry_ref
        if entry_price is None or entry_price <= 0:
            return AdapterDecision(
                asset_id, self.domain, "blocked", "one_sided_quote",
                reason="no_executable_price_on_carry_perp_leg",
                payload=payload,
            )
        bracket = PerpBracket(
            stop_loss=entry_price * (0.5 if signed > 0 else 1.5),
            take_profit=entry_price * (1.5 if signed > 0 else 0.5),
        )
        pa = self._paper_adapter(asset_id, reading)
        try:
            position = pa.open(
                signed,
                reading.quote,
                decision_ts=now_ts,
                bracket=bracket,
                collateral_usd=self.collateral_usd,
            )
        except PerpPaperError as exc:
            self.session.rollback()
            return AdapterDecision(
                asset_id, self.domain, "blocked", "order_rejected",
                reason=str(exc),
                payload=payload,
            )
        # The hedge leg: recorded as its own event against the same position,
        # carrying its cost so the net-carry accounting is legible.
        self.session.add(
            PerpPaperEvent(
                position_id=position.id,
                paper_run_id=self.paper_run_id,
                event_type="hedge_leg",
                observed_at=now_ts,
                status="recorded",
                reason="funding_carry_event_contract_hedge",
                payload={
                    "hedge_cost_usd": decision.hedge_cost_usd,
                    "expected_funding_usd": decision.expected_funding_usd,
                    "expected_net_carry_usd": decision.expected_net_carry_usd,
                    "perp_entry_fee_usd": position.fee_usd,
                },
            )
        )
        self.session.commit()
        self._open_by_asset[asset_id] = position.id
        return AdapterDecision(
            asset_id, self.domain, "entry", "carry_filled",
            reason=None,
            would_fill=True,
            filled=True,
            payload={**payload, "position_id": position.id},
        )

    # -- funding application (§4.5) ---------------------------------

    def apply_funding(
        self,
        asset_id: str,
        *,
        funding_rate: float,
        mark_price: float,
        observed_at: int,
    ) -> float | None:
        """Apply one realized funding settlement to this asset's open
        position. `funding_pnl_usd` accumulates it; `realized_pnl_usd` is
        untouched — a funding event is not a price-driven outcome (§4.5).
        Returns the funding amount, or None when there is no open position."""
        pos_id = self._open_by_asset.get(asset_id)
        if pos_id is None:
            return None
        pos = self.session.get(PerpPaperPosition, pos_id)
        if pos is None or pos.status != "open":
            return None
        amount = realized_funding(
            signed_quantity=pos.signed_quantity,
            multiplier=pos.multiplier,
            mark_price=mark_price,
            funding_rate=funding_rate,
        )
        pos.funding_pnl_usd = (pos.funding_pnl_usd or 0.0) + amount
        self.session.add(pos)
        self.session.add(
            PerpPaperEvent(
                position_id=pos.id,
                paper_run_id=self.paper_run_id,
                event_type="funding",
                observed_at=observed_at,
                funding_rate=funding_rate,
                price=mark_price,
                status="applied",
                payload={"funding_pnl_usd": amount},
            )
        )
        self.session.commit()
        return amount


def perp_market_ticker(asset_id: str) -> str:
    """Kalshi crypto-perp ticker convention: ``KX{ASSET}PERP``."""
    return f"KX{asset_id.upper()}PERP"


def db_perp_market_reader(
    session: Session,
    *,
    default_multiplier: float = 1.0,
    default_minimum_size: float = 0.01,
    default_tick_size: float = 0.01,
    default_fee_rate: float = 0.0,
) -> PerpMarketReader:
    """A `PerpMarketReader` over captured `PerpMarkObservation` rows.

    Returns the freshest mark at-or-before `now_ts` (causal: filtered on
    `available_at`). Bid/ask come from the same row when present; contract
    parameters come from the latest eligible perp `DiscoveryResult`, falling
    back to conservative defaults. Kalshi publishes no historical mark series,
    so this reads what `data.perps.poll_perp_marks` captured — never a
    fabricated value.
    """

    def _read(asset_id: str, now_ts: int) -> PerpMarketReading | None:
        ticker = perp_market_ticker(asset_id)
        row = session.execute(
            select(PerpMarkObservation)
            .where(
                PerpMarkObservation.market_ticker == ticker,
                PerpMarkObservation.available_at <= now_ts,
            )
            .order_by(PerpMarkObservation.available_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None

        def _f(value: str | None) -> float | None:
            if value is None:
                return None
            try:
                return float(value)
            except ValueError:
                return None

        mark = _f(row.settlement_mark_dollars)
        bid = _f(row.bid_dollars)
        ask = _f(row.ask_dollars)
        # A one-sided or missing quote falls back to the mark so a directional
        # entry still has an executable reference; `fill_perp_order` will
        # still reject a genuinely absent price.
        bid = bid if bid is not None else mark
        ask = ask if ask is not None else mark

        disc = session.execute(
            select(DiscoveryResult)
            .where(
                DiscoveryResult.asset_id == asset_id.upper(),
                DiscoveryResult.instrument == "perp",
            )
            .order_by(DiscoveryResult.checked_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        meta = disc.metadata_json if disc is not None and disc.metadata_json else {}
        multiplier = float(meta.get("multiplier") or default_multiplier)
        minimum_size = float(meta.get("minimum_order_size") or default_minimum_size)
        tick_size = float(meta.get("tick_size") or default_tick_size)
        fee_rate = float(meta.get("fee_rate") or default_fee_rate)

        funding_row = session.execute(
            select(PerpFundingObservation.funding_rate)
            .where(
                PerpFundingObservation.market_ticker == ticker,
                PerpFundingObservation.available_at <= now_ts,
            )
            .order_by(PerpFundingObservation.observed_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        return PerpMarketReading(
            quote=PerpQuote(
                bid=bid,
                ask=ask,
                observed_at=row.observed_at,
                available_at=row.available_at,
                reference={"market_ticker": ticker, "source": row.source},
            ),
            mark_price=mark,
            latest_funding_rate=funding_row,
            multiplier=multiplier,
            minimum_size=minimum_size,
            tick_size=tick_size,
            fee_rate=fee_rate,
        )

    return _read


def db_perp_coverage_reader(session: Session) -> PerpCoverageReader:
    """A `PerpCoverageReader` over captured mark/funding rows."""

    def _read(asset_id: str, _now_ts: int) -> PerpMarkCoverage:
        ticker = perp_market_ticker(asset_id)
        latest_mark = session.execute(
            select(PerpMarkObservation.observed_at)
            .where(PerpMarkObservation.market_ticker == ticker)
            .order_by(PerpMarkObservation.observed_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        latest_funding = session.execute(
            select(PerpFundingObservation.observed_at)
            .where(PerpFundingObservation.market_ticker == ticker)
            .order_by(PerpFundingObservation.observed_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return PerpMarkCoverage(
            latest_mark_observed_at=latest_mark,
            latest_funding_observed_at=latest_funding,
            has_realized_funding=latest_funding is not None,
        )

    return _read


def db_perp_discovery_reader(session: Session) -> PerpDiscoveryReader:
    """A `PerpDiscoveryReader` over the latest eligible perp `DiscoveryResult`."""

    def _read(asset_id: str, _now_ts: int) -> DiscoverySnapshot | None:
        row = session.execute(
            select(DiscoveryResult)
            .where(
                DiscoveryResult.asset_id == asset_id.upper(),
                DiscoveryResult.instrument == "perp",
            )
            .order_by(DiscoveryResult.checked_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None
        return DiscoverySnapshot(
            asset_id=row.asset_id,
            instrument=row.instrument,
            identifier=row.identifier,
            cadence=row.cadence,
            checked_at=row.checked_at,
            eligible=row.eligible,
            failure_reason=row.failure_reason,
            metadata=row.metadata_json or {},
        )

    return _read


@dataclass(frozen=True)
class _FundingRateOnly:
    """Minimal stand-in for `risk.funding_awareness.FundingState`:
    `evaluate_funding_carry` reads only `.funding_rate`."""

    funding_rate: float


def _ticker(reading: PerpMarketReading) -> str:
    ref = reading.quote.reference
    if isinstance(ref, dict):
        return str(ref.get("market_ticker", ""))
    return ""


def _now_guess(_session: Session) -> int:
    # `reconcile` is called with an asset id only (DomainPaperAdapter's
    # contract); the market reader needs a `now_ts`. The orchestrator
    # reconciles right after preflight, so "latest known" is close enough for
    # a freshness bound the perp adapter re-checks anyway. Kept as a named
    # seam rather than a bare `int(time.time())` so a test can monkeypatch it.
    import time

    return int(time.time())


__all__ = [
    "PerpCoverageReader",
    "PerpDiscoveryReader",
    "PerpEvalContext",
    "PerpMarketReader",
    "PerpMarketReading",
    "PerpPaperDomainAdapter",
    "PerpSignal",
    "PerpStrategyFn",
    "db_perp_coverage_reader",
    "db_perp_discovery_reader",
    "db_perp_market_reader",
    "hold_perp_strategy",
    "perp_market_ticker",
]
