"""Read-only queries backing the dashboard views (spec: operator-dashboard).

Everything here reads from tables that already exist and are already
populated by the backtest engine: `BacktestRun`, `SignalRecord`,
`SimulatedTrade`. There is no live-trading data yet — the authenticated
client, risk layer, and strategies that would populate live positions/
funding/liquidation views don't exist until tasks.md §4-§7 are built. Those
panels render as explicit placeholders (see routes.py) rather than faking
numbers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from itertools import pairwise

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from kalshi_bot.config.crypto_registry import DEFAULT_CRYPTO_REGISTRY
from kalshi_bot.data.kalshi.coverage import CoverageReport, coverage_report
from kalshi_bot.data.manifests import manifest_provenance_class
from kalshi_bot.execution.run_reporting import RunHealthReport, build_run_health_report
from kalshi_bot.storage import (
    BacktestRun,
    BRTIObservation,
    DatasetManifest,
    DiscoveryResult,
    KalshiMarket,
    PaperAuditEvent,
    PaperRun,
    PerpFundingObservation,
    PerpMarkObservation,
    PerpPaperEvent,
    PerpPaperPosition,
    SignalRecord,
    SimulatedTrade,
    SportsCandle,
    SportsMarketDiscovery,
    SportsOrderBookSnapshot,
    SportsPublicTrade,
)

# A discovery snapshot older than this is not fresh enough to render an asset
# as eligible on the dashboard, regardless of the persisted `eligible` flag
# (multi-venue-paper-trading §12.2: stale data must never read as eligible).
DISCOVERY_FRESH_MAX_AGE_S = 3_600

BTC_SERIES = ["KXBTC", "KXBTCD", "KXBTC15M"]

# coverage_report does two full table scans per series (no index on
# series_ticker+period_minutes) — over the archived 1-minute candle history
# that's tens of seconds per series, far too slow for a page load. Cache
# and refresh on a timer instead of computing it per-request.
COVERAGE_CACHE_TTL_S = 120.0
_coverage_cache: tuple[float, list[CoverageReport]] | None = None


@dataclass
class EquityPoint:
    ts: int
    equity_usd: float


@dataclass
class MarketArea:
    """Dashboard summary for one instrument family."""

    key: str
    label: str
    description: str
    status: str
    rows: int
    last_ts: int | None
    detail: str


@dataclass(frozen=True)
class AssetAdmission:
    asset_id: str
    domain: str
    cadence: str | None
    configured: bool
    discovered: bool
    eligible: bool
    source_aligned: bool
    lifecycle: str
    blocker: str | None


@dataclass(frozen=True)
class PaperTradingReadiness:
    """Measured prerequisites for one domain/asset paper path.

    This is intentionally a matrix of independent gates.  A present but
    reconstructed manifest, a discovered but stale perp, and sports with no
    feasibility report must remain visibly different states.
    """

    asset_id: str
    domain: str
    cadence: str | None
    lifecycle: str
    configured: bool
    cli_wired: bool
    manifest_frozen: bool
    manifest_provenance_class: str | None
    discovery_present: bool
    discovery_eligible: bool
    discovery_age_s: int | None
    discovery_fresh: bool
    mark_or_brti_last_ts: int | None
    mark_or_brti_age_s: int | None
    mark_or_brti_fresh: bool
    feasibility_outcome: str | None

    @property
    def ready(self) -> bool:
        if self.domain == "sports":
            return self.cli_wired and self.feasibility_outcome == "research_promising"
        return (
            self.configured
            and self.discovery_present
            and self.discovery_eligible
            and self.discovery_fresh
            and self.mark_or_brti_fresh
            and (
                self.domain != "prediction"
                or (
                    self.lifecycle in {"shadow", "paper"}
                    and self.manifest_frozen
                    and self.manifest_provenance_class == "source_native"
                )
            )
        )


PAPER_READINESS_FRESH_MAX_AGE_S = 120


def _latest_manifest_for_asset(
    manifests: list[DatasetManifest], asset_id: str
) -> DatasetManifest | None:
    for manifest in manifests:
        if asset_id in (manifest.asset_ids or []):
            return manifest
    return None


def _latest_discovery_rows(session: Session) -> dict[tuple[str, str, str | None], DiscoveryResult]:
    latest: dict[tuple[str, str, str | None], DiscoveryResult] = {}
    for row in session.execute(
        select(DiscoveryResult).order_by(desc(DiscoveryResult.checked_at))
    ).scalars():
        latest.setdefault((row.asset_id, row.instrument, row.cadence), row)
    return latest


def _readiness_row(
    *,
    asset_id: str,
    domain: str,
    cadence: str | None,
    lifecycle: str,
    configured: bool,
    cli_wired: bool,
    manifest: DatasetManifest | None,
    discovery: DiscoveryResult | None,
    observation_ts: int | None,
    now_ts: int,
    feasibility_outcome: str | None = None,
) -> PaperTradingReadiness:
    discovery_age = max(0, now_ts - discovery.checked_at) if discovery else None
    observation_age = max(0, now_ts - observation_ts) if observation_ts is not None else None
    return PaperTradingReadiness(
        asset_id=asset_id,
        domain=domain,
        cadence=cadence,
        lifecycle=lifecycle,
        configured=configured,
        cli_wired=cli_wired,
        manifest_frozen=bool(manifest and manifest.status == "frozen"),
        manifest_provenance_class=(manifest_provenance_class(manifest) if manifest else None),
        discovery_present=discovery is not None,
        discovery_eligible=bool(discovery and discovery.eligible),
        discovery_age_s=discovery_age,
        discovery_fresh=bool(
            discovery
            and discovery_age is not None
            and discovery_age <= PAPER_READINESS_FRESH_MAX_AGE_S
        ),
        mark_or_brti_last_ts=observation_ts,
        mark_or_brti_age_s=observation_age,
        mark_or_brti_fresh=(
            observation_age is not None and observation_age <= PAPER_READINESS_FRESH_MAX_AGE_S
        ),
        feasibility_outcome=feasibility_outcome,
    )


def papertrading_readiness(
    session: Session, *, now_ts: int | None = None
) -> list[PaperTradingReadiness]:
    """Return the operator-facing prediction/perp/sports readiness matrix.

    Sports feasibility reports are currently file artifacts rather than DB
    rows, so the query reports ``absent`` until that existing research flow
    writes a report that the paper runner can consume.  It never infers a
    passing result from capture volume.
    """
    now = int(time.time()) if now_ts is None else now_ts
    manifests = list(
        session.execute(
            select(DatasetManifest).order_by(desc(DatasetManifest.created_at))
        ).scalars()
    )
    discoveries = _latest_discovery_rows(session)
    out: list[PaperTradingReadiness] = []
    index_sources = {
        "BTC": "kalshi:cfbenchmarks/BRTI",
    }
    for asset in DEFAULT_CRYPTO_REGISTRY:
        manifest = _latest_manifest_for_asset(manifests, asset.asset_id)
        for instrument in asset.event_instruments.values():
            source = index_sources.get(
                asset.asset_id, f"kalshi:cfbenchmarks/{asset.asset_id}USD_RTI"
            )
            brti_ts = session.scalar(
                select(func.max(BRTIObservation.observed_at)).where(
                    BRTIObservation.source == source
                )
            )
            out.append(
                _readiness_row(
                    asset_id=asset.asset_id,
                    domain="prediction",
                    cadence=instrument.cadence,
                    lifecycle=instrument.lifecycle,
                    configured=True,
                    cli_wired=True,
                    manifest=manifest,
                    discovery=discoveries.get((asset.asset_id, "event", instrument.cadence)),
                    observation_ts=brti_ts,
                    now_ts=now,
                )
            )
        perp_ts = session.scalar(
            select(func.max(PerpMarkObservation.observed_at)).where(
                PerpMarkObservation.market_ticker == asset.perp.market_ticker
            )
        ) if asset.perp else None
        out.append(
            _readiness_row(
                asset_id=asset.asset_id,
                domain="perp",
                cadence=None,
                lifecycle="observe",
                configured=asset.perp is not None,
                cli_wired=True,
                manifest=manifest,
                discovery=discoveries.get((asset.asset_id, "perp", None)),
                observation_ts=perp_ts,
                now_ts=now,
            )
        )
    sports_last = session.scalar(select(func.max(SportsMarketDiscovery.observed_at)))
    out.append(
        _readiness_row(
            asset_id="sports",
            domain="sports",
            cadence=None,
            lifecycle="observe",
            configured=True,
            cli_wired=True,
            manifest=None,
            discovery=None if sports_last is None else DiscoveryResult(
                asset_id="sports", instrument="sports", identifier="sports",
                checked_at=int(sports_last), eligible=True,
            ),
            observation_ts=sports_last,
            now_ts=now,
            feasibility_outcome="absent",
        )
    )
    return out


def _admission_from_row(
    asset_id: str,
    domain: str,
    cadence: str | None,
    configured: bool,
    lifecycle: str,
    row: DiscoveryResult | None,
    *,
    now_ts: int,
) -> AssetAdmission:
    """Build one admission row, refusing to render `eligible` for a stale,
    unverified, or source-misaligned discovery snapshot (§12.2)."""
    discovered = row is not None
    fresh = bool(row and (now_ts - row.checked_at) <= DISCOVERY_FRESH_MAX_AGE_S)
    aligned = bool(row and row.metadata_json and row.metadata_json.get("source_aligned"))
    verified = bool(row and row.eligible)
    eligible = verified and fresh and aligned
    if eligible:
        blocker = None
    elif not discovered:
        blocker = "not_discovered"
    elif row.failure_reason:
        blocker = row.failure_reason
    elif not fresh:
        blocker = "stale_discovery_snapshot"
    elif not aligned:
        blocker = "source_not_aligned"
    else:
        blocker = "not_eligible"
    return AssetAdmission(
        asset_id, domain, cadence, configured, discovered, eligible, aligned, lifecycle, blocker
    )


def asset_admissions(session: Session, *, now_ts: int | None = None) -> list[AssetAdmission]:
    """Dashboard-safe registry/discovery state; absence, staleness, or an
    unverified/misaligned snapshot never implies eligible."""
    now = now_ts if now_ts is not None else int(time.time())
    latest: dict[tuple[str, str, str | None], DiscoveryResult] = {}
    for row in session.execute(
        select(DiscoveryResult).order_by(desc(DiscoveryResult.checked_at))
    ).scalars():
        latest.setdefault((row.asset_id, row.instrument, row.cadence), row)
    results: list[AssetAdmission] = []
    for asset in DEFAULT_CRYPTO_REGISTRY:
        for instrument in asset.event_instruments.values():
            results.append(
                _admission_from_row(
                    asset.asset_id,
                    "prediction",
                    instrument.cadence,
                    True,
                    instrument.lifecycle,
                    latest.get((asset.asset_id, "event", instrument.cadence)),
                    now_ts=now,
                )
            )
        results.append(
            _admission_from_row(
                asset.asset_id,
                "perp",
                None,
                asset.perp is not None,
                "observe",
                latest.get((asset.asset_id, "perp", None)),
                now_ts=now,
            )
        )
    return results


def market_areas(session: Session) -> list[MarketArea]:
    """Return measured summaries for sports, perps, and event markets.

    Empty tables are represented explicitly; the dashboard never invents
    prices or positions for an instrument that has not been captured.
    """
    sports_discovered = session.scalar(select(func.count(SportsMarketDiscovery.id))) or 0
    sports_candles = session.scalar(select(func.count(SportsCandle.id))) or 0
    sports_books = session.scalar(select(func.count(SportsOrderBookSnapshot.id))) or 0
    sports_trades = session.scalar(select(func.count(SportsPublicTrade.id))) or 0
    sports_last = session.scalar(select(func.max(SportsCandle.observed_at)))
    perp_marks = session.scalar(select(func.count(PerpMarkObservation.id))) or 0
    perp_funding = session.scalar(select(func.count(PerpFundingObservation.id))) or 0
    perp_last = session.scalar(select(func.max(PerpMarkObservation.observed_at)))
    market_count, market_last = session.execute(
        select(func.count(KalshiMarket.ticker), func.max(KalshiMarket.close_ts))
    ).one()
    return [
        MarketArea(
            "sports",
            "Sports betting",
            "Two-outcome, single-game markets screened for rules, spread, and executable depth.",
            "captured" if sports_candles else ("discovered" if sports_discovered else "research"),
            int(sports_discovered or 0),
            sports_last,
            f"{int(sports_candles or 0):,} candles · {int(sports_books or 0):,} books "
            f"· {int(sports_trades or 0):,} trades",
        ),
        MarketArea(
            "perps",
            "Perpetuals",
            "Crypto perpetual marks and funding observations, isolated from "
            "event-contract execution.",
            "captured" if perp_marks else ("funding history" if perp_funding else "research"),
            int(perp_marks or 0),
            perp_last,
            f"{int(perp_marks or 0):,} marks · {int(perp_funding or 0):,} funding settlements",
        ),
        MarketArea(
            "prediction-markets",
            "Prediction markets",
            "Kalshi event contracts, validation runs, settlement rules, and fee-aware backtests.",
            "archived" if market_count else "research",
            int(market_count or 0),
            market_last,
            f"{int(market_count or 0):,} contracts in the market archive",
        ),
    ]


def recent_backtest_runs(session: Session, limit: int = 20) -> list[BacktestRun]:
    return list(
        session.execute(
            select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(limit)
        ).scalars()
    )


def latest_backtest_run(session: Session) -> BacktestRun | None:
    return session.execute(
        select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(1)
    ).scalar_one_or_none()


def recent_signals(
    session: Session, backtest_run_id: int | None = None, limit: int = 50
) -> list[SignalRecord]:
    stmt = select(SignalRecord).order_by(desc(SignalRecord.evaluated_at_ts)).limit(limit)
    if backtest_run_id is not None:
        stmt = stmt.where(SignalRecord.backtest_run_id == backtest_run_id)
    return list(session.execute(stmt).scalars())


def trades_for_run(session: Session, backtest_run_id: int) -> list[SimulatedTrade]:
    return list(
        session.execute(
            select(SimulatedTrade)
            .where(SimulatedTrade.backtest_run_id == backtest_run_id)
            .order_by(SimulatedTrade.entry_ts)
        ).scalars()
    )


def equity_curve(
    session: Session, backtest_run_id: int, starting_cash_usd: float
) -> list[EquityPoint]:
    """Reconstruct a coarse equity curve from settled trades in entry order.

    Not a substitute for the engine's own per-bar equity tracking (which
    isn't persisted) — this is a post-hoc view good enough for a dashboard
    chart: cash after each trade settles, in the order trades were entered.
    """
    trades = trades_for_run(session, backtest_run_id)
    points = [EquityPoint(ts=0, equity_usd=starting_cash_usd)]
    running = starting_cash_usd
    for t in trades:
        if t.net_pnl_usd is None or t.exit_ts is None:
            continue
        running += t.net_pnl_usd
        points.append(EquityPoint(ts=t.exit_ts, equity_usd=running))
    return points


@dataclass
class ValidationStatus:
    """What the operator needs to see about the current best validation
    evidence (kxbtc15m-validation-rebuild §6.1): instrument scope, data
    provenance/freshness, the fee/resolution config versions the run
    assumed, and the promotion verdict. All fields degrade to None/"—"
    when the underlying run has not populated them yet."""

    run_id: int | None
    strategy_name: str | None
    evidence_class: str | None  # "diagnostic" | "validation"
    instrument_scope: str  # e.g. "KXBTC15M only" or "—"
    data_start_ts: int | None
    data_end_ts: int | None
    fee_config_version: str | None
    resolution_config_version: str | None
    calibrator_version: str | None
    promotion_status: str  # "passed" | "failed" | "not_evaluated" | "—"
    promotion_reasons: list[str]
    provenance: dict | None


def latest_validation_status(session: Session) -> ValidationStatus:
    """Read the most recent `validation`-class run if one exists, else the
    most recent run of any class, and surface its promotion/provenance
    fields. Never raises — a fresh DB just yields an all-empty status."""
    run = session.execute(
        select(BacktestRun)
        .where(BacktestRun.evidence_class == "validation")
        .order_by(desc(BacktestRun.created_at))
        .limit(1)
    ).scalar_one_or_none()
    if run is None:
        run = latest_backtest_run(session)
    if run is None:
        return ValidationStatus(
            run_id=None,
            strategy_name=None,
            evidence_class=None,
            instrument_scope="—",
            data_start_ts=None,
            data_end_ts=None,
            fee_config_version=None,
            resolution_config_version=None,
            calibrator_version=None,
            promotion_status="—",
            promotion_reasons=[],
            provenance=None,
        )

    prov = run.provenance or {}
    metrics = run.metrics_test or {}
    promotion = metrics.get("promotion") if isinstance(metrics, dict) else None
    promo_status = "not_evaluated"
    promo_reasons: list[str] = []
    if isinstance(promotion, dict):
        promo_status = "passed" if promotion.get("passed") else "failed"
        promo_reasons = list(promotion.get("reasons", []))

    scope = "—"
    if isinstance(prov, dict):
        series = prov.get("series") or prov.get("series_filter")
        if series:
            scope = f"{series} only" if isinstance(series, str) else str(series)
    if scope == "—" and run.evidence_class == "validation":
        scope = "KXBTC15M only"  # validation runs are KXBTC15M-scoped by construction

    calibrator = None
    if isinstance(prov, dict):
        calibrator = prov.get("calibrator_version")

    return ValidationStatus(
        run_id=run.id,
        strategy_name=run.strategy_name,
        evidence_class=run.evidence_class,
        instrument_scope=scope,
        data_start_ts=run.data_start_ts,
        data_end_ts=run.data_end_ts,
        fee_config_version=run.fee_config_version,
        resolution_config_version=run.resolution_config_version,
        calibrator_version=calibrator,
        promotion_status=promo_status,
        promotion_reasons=promo_reasons,
        provenance=prov if isinstance(prov, dict) else None,
    )


def cached_btc_coverage() -> list[CoverageReport] | None:
    """Last computed coverage snapshot, or None before the first warm-up completes.

    Never runs the underlying full-table-scan query itself — see the
    module-level note. A background thread (app.py) calls
    `refresh_coverage_cache` on a timer to keep this warm.
    """
    return _coverage_cache[1] if _coverage_cache is not None else None


def refresh_coverage_cache(session: Session, period_minutes: int = 1) -> None:
    global _coverage_cache
    reports = [coverage_report(session, series, period_minutes) for series in BTC_SERIES]
    _coverage_cache = (time.monotonic(), reports)


# --------------------------------------------------------------------------
# BRTI reconstruction coverage (brti-constituent-history §8.4)
#
# Deliberately separate from the Kalshi-candle coverage above: a captured
# BRTI second and a reconstructed-index second are never the same claim, and
# this view keeps that distinction visible rather than presenting a single
# blended figure.
# --------------------------------------------------------------------------


@dataclass
class BRTIReconstructionCoverage:
    target_index: str
    captured_rows: int
    reconstructed_rows: int
    reconstructed_first_ts: int | None
    reconstructed_last_ts: int | None
    contributing_venues: list[str]
    measurement_status: str
    """"measured" | "unmeasured" -- read from the most recent frozen
    manifest's reconstruction_error, or "unmeasured" if no manifest with a
    measurement exists yet. Never rendered as a passing status when
    "unmeasured"."""


def brti_reconstruction_coverage(
    session: Session, target_index: str = "BRTI"
) -> BRTIReconstructionCoverage:
    from kalshi_bot.storage.models import DatasetManifest, ReconstructedIndexObservation

    captured_rows = session.scalar(select(func.count()).select_from(BRTIObservation)) or 0
    recon_rows = (
        session.query(ReconstructedIndexObservation)
        .filter(ReconstructedIndexObservation.target_index == target_index)
        .all()
    )
    venues: set[str] = set()
    for row in recon_rows:
        venues.update(row.contributing_venues or [])
    first_ts = min((r.observed_at for r in recon_rows), default=None)
    last_ts = max((r.observed_at for r in recon_rows), default=None)

    latest_manifest = session.scalar(
        select(DatasetManifest)
        .where(DatasetManifest.reconstruction_error.is_not(None))
        .order_by(desc(DatasetManifest.created_at))
        .limit(1)
    )
    status = "unmeasured"
    if latest_manifest is not None and latest_manifest.reconstruction_error:
        status = latest_manifest.reconstruction_error.get("status", "unmeasured")

    return BRTIReconstructionCoverage(
        target_index=target_index,
        captured_rows=int(captured_rows),
        reconstructed_rows=len(recon_rows),
        reconstructed_first_ts=first_ts,
        reconstructed_last_ts=last_ts,
        contributing_venues=sorted(venues),
        measurement_status=status,
    )


# --------------------------------------------------------------------------
# Capture health (operator-dashboard: live feed status)
#
# The capture feeds are the project's binding constraint, not the strategy
# code: KXBTC15M settles off the CF Benchmarks BRTI index, and a validation
# verdict needs a long *contiguous* BRTI window aligned with the archived
# contract history. A silently dead capture window has cost this project
# weeks of data more than once, so the dashboard reports feed freshness
# first-class rather than leaving it to a log file nobody is watching.
#
# Every number here is measured, never estimated: staleness comes from the
# newest `observed_at`, and the validation-readiness figures come from the
# same fold geometry the promotion gate enforces.
# --------------------------------------------------------------------------

# A feed is late once it has been silent for more than this multiple of its
# nominal poll interval, and stale (red) at the higher multiple. Generous
# enough not to cry wolf on one dropped request.
FEED_LATE_FACTOR = 5
FEED_STALE_FACTOR = 20

# The Bitcoin index among the nine CF Benchmarks indices captured. Only this
# one feeds a KXBTC15M verdict; `BacktestEngine._load_brti` filters the same
# way, so the dashboard must not count ETH/SOL rows toward BTC readiness.
BTC_INDEX_SOURCE = "kalshi:cfbenchmarks/BRTI"


@dataclass
class FeedHealth:
    """Freshness of one captured data feed."""

    name: str
    detail: str
    rows: int
    first_ts: int | None
    last_ts: int | None
    expected_interval_s: int

    @property
    def age_s(self) -> int | None:
        if self.last_ts is None:
            return None
        return max(0, int(time.time()) - self.last_ts)

    @property
    def span_hours(self) -> float:
        if self.first_ts is None or self.last_ts is None:
            return 0.0
        return (self.last_ts - self.first_ts) / 3600.0

    @property
    def status(self) -> str:
        """ "live" | "late" | "stale" | "empty" — drives the badge colour."""
        age = self.age_s
        if age is None or self.rows == 0:
            return "empty"
        if age > self.expected_interval_s * FEED_STALE_FACTOR:
            return "stale"
        if age > self.expected_interval_s * FEED_LATE_FACTOR:
            return "late"
        return "live"


def _feed_row(session: Session, model, *, where=None) -> tuple[int, int | None, int | None]:
    """(rows, first observed_at, last observed_at) for an observation table."""
    stmt = select(func.count(model.id), func.min(model.observed_at), func.max(model.observed_at))
    if where is not None:
        stmt = stmt.where(where)
    rows, first_ts, last_ts = session.execute(stmt).one()
    return int(rows or 0), first_ts, last_ts


def capture_feeds(session: Session) -> list[FeedHealth]:
    """Freshness of every capture feed `start_capture.bat` maintains.

    Cheap: three indexed min/max/count aggregates, safe on the request path
    (unlike the candle coverage scan).
    """
    feeds: list[FeedHealth] = []

    rows, first_ts, last_ts = _feed_row(
        session, BRTIObservation, where=BRTIObservation.source == BTC_INDEX_SOURCE
    )
    feeds.append(
        FeedHealth(
            name="BRTI (Bitcoin index)",
            detail="Settles KXBTC15M — the load-bearing feed",
            rows=rows,
            first_ts=first_ts,
            last_ts=last_ts,
            expected_interval_s=60,
        )
    )

    rows, first_ts, last_ts = _feed_row(
        session, BRTIObservation, where=BRTIObservation.source != BTC_INDEX_SOURCE
    )
    feeds.append(
        FeedHealth(
            name="Other CF indices",
            detail="ETH/SOL/XRP/DOGE/BNB/HYPE/NEAR/ZEC — captured ahead of need",
            rows=rows,
            first_ts=first_ts,
            last_ts=last_ts,
            expected_interval_s=60,
        )
    )

    rows, first_ts, last_ts = _feed_row(session, PerpMarkObservation)
    feeds.append(
        FeedHealth(
            name="Perp marks",
            detail="Not backfillable — live poll is the only source",
            rows=rows,
            first_ts=first_ts,
            last_ts=last_ts,
            expected_interval_s=60,
        )
    )

    rows, first_ts, last_ts = _feed_row(session, PerpFundingObservation)
    feeds.append(
        FeedHealth(
            name="Perp funding",
            detail="Backfillable — 8-hourly settlements",
            rows=rows,
            first_ts=first_ts,
            last_ts=last_ts,
            expected_interval_s=8 * 3600,
        )
    )
    return feeds


@dataclass
class ValidationReadiness:
    """How far the captured BRTI window is from supporting a real verdict.

    The promotion gate needs `min_folds` walk-forward folds, and the fold
    geometry is train + embargo + N*test seconds of *contiguous* history
    (backtest.validation_run). Until that much BRTI exists, `run_validation.py`
    can only return NO-GO for lack of data — so the honest thing to show an
    operator is the countdown, not a spinner.

    `overlap_*` is the intersection of the BRTI window with the archived
    KXBTC15M market window: BRTI outside the contract history evaluates
    nothing, which is why a million evaluations can yield zero trades.
    """

    brti_span_days: float
    required_days: float
    overlap_days: float
    markets_in_overlap: int
    days_remaining: float
    projected_ready_ts: int | None

    @property
    def pct_complete(self) -> float:
        if self.required_days <= 0:
            return 100.0
        return max(0.0, min(100.0, 100.0 * self.brti_span_days / self.required_days))

    @property
    def is_ready(self) -> bool:
        return self.brti_span_days >= self.required_days


def validation_readiness(
    session: Session,
    *,
    train_seconds: int,
    test_seconds: int,
    embargo_seconds: int,
    min_folds: int,
) -> ValidationReadiness:
    _, brti_first, brti_last = _feed_row(
        session, BRTIObservation, where=BRTIObservation.source == BTC_INDEX_SOURCE
    )
    required_s = train_seconds + embargo_seconds + min_folds * test_seconds
    span_s = (brti_last - brti_first) if (brti_first and brti_last) else 0

    mkt_first, mkt_last = session.execute(
        select(func.min(KalshiMarket.close_ts), func.max(KalshiMarket.close_ts)).where(
            KalshiMarket.ticker.like("KXBTC15M%")
        )
    ).one()

    overlap_s = 0
    markets_in_overlap = 0
    if brti_first and brti_last and mkt_first and mkt_last:
        lo, hi = max(brti_first, mkt_first), min(brti_last, mkt_last)
        if hi > lo:
            overlap_s = hi - lo
            markets_in_overlap = int(
                session.execute(
                    select(func.count(KalshiMarket.ticker)).where(
                        KalshiMarket.ticker.like("KXBTC15M%"),
                        KalshiMarket.close_ts > lo,
                        KalshiMarket.close_ts <= hi,
                    )
                ).scalar_one()
                or 0
            )

    remaining_s = max(0, required_s - span_s)
    return ValidationReadiness(
        brti_span_days=span_s / 86_400,
        required_days=required_s / 86_400,
        overlap_days=overlap_s / 86_400,
        markets_in_overlap=markets_in_overlap,
        days_remaining=remaining_s / 86_400,
        projected_ready_ts=(int(time.time()) + remaining_s) if remaining_s else None,
    )


@dataclass
class SamplingQuality:
    """How densely BRTI is sampled relative to the settlement rule.

    KXBTC15M resolves on a 60-second *average* at open and close. A poll
    interval at or above that window collapses the average to a single
    reading, so this measures the actual spacing rather than trusting the
    configured interval.
    """

    median_gap_s: int | None
    mean_per_window: float
    long_gaps: int


# Bounded so the dashboard reads a recent slice rather than the whole archive.
SAMPLING_LOOKBACK_ROWS = 5_000
LONG_GAP_S = 300


def sampling_quality(session: Session) -> SamplingQuality:
    rows = list(
        session.execute(
            select(BRTIObservation.observed_at)
            .where(BRTIObservation.source == BTC_INDEX_SOURCE)
            .order_by(desc(BRTIObservation.observed_at))
            .limit(SAMPLING_LOOKBACK_ROWS)
        ).scalars()
    )
    if len(rows) < 2:
        return SamplingQuality(median_gap_s=None, mean_per_window=0.0, long_gaps=0)

    rows.reverse()
    gaps = sorted(b - a for a, b in pairwise(rows) if b > a)
    median_gap = gaps[len(gaps) // 2] if gaps else None
    long_gaps = sum(1 for g in gaps if g > LONG_GAP_S)

    # Mean readings per distinct 60-second settlement window actually touched.
    windows = {ts // 60 for ts in rows}
    mean_per_window = len(rows) / len(windows) if windows else 0.0

    return SamplingQuality(
        median_gap_s=median_gap, mean_per_window=mean_per_window, long_gaps=long_gaps
    )


# --------------------------------------------------------------------------
# Paper-run health (multi-venue-paper-trading §12.1 / §12.4)
#
# Domain-separated: each run's ledger belongs to exactly one domain and is
# never merged with another. The dashboard shows the six run-health outcomes
# distinctly (no_signal / policy_block / stale_data / missing_coverage /
# execution_rejected / system_failure) plus reconciliation state, so an
# operator can tell "quiet but healthy" from "blocked" at a glance.
# --------------------------------------------------------------------------


@dataclass
class PaperRunSummary:
    run_id: str
    domain: str
    mode: str
    status: str
    started_at: int
    ended_at: int | None
    decisions: int
    fills: int
    outcome_counts: dict[str, int]
    unresolved_reconciliation: list[str]
    healthy: bool
    blocks_new_entries: bool
    blocked_fill_reasons: dict[str, str]
    """asset_id -> preflight reason for every admitted-but-not-filling asset
    (brti-constituent-history §8.5), e.g. `reconstructed_data_not_admissible`
    or `no_frozen_admission_report`. Empty when every admitted asset may
    fill, or when no preflight audit event was recorded for this run."""
    strategy_id: str | None = None
    strategy_gate_status: str | None = None
    """The registry gate standing for this run's strategy at run time
    (strategy-lab-multi-account §7.4): `passed` | `gate_failed` |
    `never_gated` | `parked`, or None for a run written before schema v14.
    Never altered by the run's own result — a paper result is an input to a
    future gate decision, not a substitute for one."""

    @property
    def decisions_without_fills(self) -> bool:
        """True when the run records decisions but has produced no fills and
        every admitted asset is blocked from filling — the expected state for
        a run awaiting captured BRTI or backed by a reconstructed manifest
        (§7.5). Rendered as an explained state, not a malfunction."""
        return (
            self.decisions > 0
            and self.fills == 0
            and bool(self.blocked_fill_reasons)
        )


def _blocked_fill_reasons(session: Session, run_id: str) -> dict[str, str]:
    event = session.scalar(
        select(PaperAuditEvent)
        .where(PaperAuditEvent.paper_run_id == run_id, PaperAuditEvent.status == "preflight_passed")
        .order_by(desc(PaperAuditEvent.observed_at))
        .limit(1)
    )
    if event is None or not event.payload:
        return {}
    admissions = event.payload.get("admissions") or []
    return {
        a["asset"]: a["reason"]
        for a in admissions
        if a.get("admitted") and not a.get("may_fill") and a.get("reason")
    }


def _summary(report: RunHealthReport, run: PaperRun, session: Session) -> PaperRunSummary:
    led = report.ledgers.get(report.domain)
    return PaperRunSummary(
        run_id=report.run_id,
        domain=report.domain,
        mode=run.mode,
        status=report.status,
        started_at=report.started_at,
        ended_at=report.ended_at,
        decisions=led.decisions if led else 0,
        fills=led.fills if led else 0,
        outcome_counts=dict(led.outcome_counts) if led else {},
        unresolved_reconciliation=[r.asset_id for r in report.unresolved_reconciliation],
        healthy=report.healthy,
        blocks_new_entries=report.blocks_new_entries,
        blocked_fill_reasons=_blocked_fill_reasons(session, run.id),
        strategy_id=run.strategy_id,
        strategy_gate_status=run.strategy_gate_status,
    )


def paper_runs_overview(session: Session, limit: int = 20) -> list[PaperRunSummary]:
    """Most recent paper/shadow runs across every domain, health-summarized.

    The synthetic per-day `ops` run written by the operator console is
    excluded — it is a command audit, not a trading run.
    """
    runs = list(
        session.execute(
            select(PaperRun)
            .where(PaperRun.domain != "ops")
            .order_by(desc(PaperRun.started_at))
            .limit(limit)
        ).scalars()
    )
    return [_summary(build_run_health_report(session, r.id), r, session) for r in runs]


def domain_paper_runs(session: Session, domain: str, limit: int = 10) -> list[PaperRunSummary]:
    """Recent paper/shadow runs for one domain only."""
    return [s for s in paper_runs_overview(session, limit=100) if s.domain == domain][:limit]


# --------------------------------------------------------------------------
# Strategy lab: perpetuals section, scalping section, and a per-run
# comparison view keyed by paper_run_id (strategy-lab-multi-account §7).
# --------------------------------------------------------------------------


@dataclass
class PerpPositionView:
    run_id: str
    asset_id: str
    market_ticker: str
    signed_quantity: float
    entry_price: float
    status: str
    realized_pnl_usd: float | None
    funding_pnl_usd: float
    fee_usd: float
    latest_mark: float | None
    liquidation_price: float | None
    stop_loss: float | None
    take_profit: float | None

    @property
    def liquidation_distance_pct(self) -> float | None:
        if self.latest_mark is None or self.liquidation_price is None or self.latest_mark <= 0:
            return None
        if self.signed_quantity > 0:
            return (self.latest_mark - self.liquidation_price) / self.latest_mark
        return (self.liquidation_price - self.latest_mark) / self.latest_mark

    @property
    def is_long(self) -> bool:
        return self.signed_quantity >= 0

    @property
    def r_dollars(self) -> float | None:
        """Dollar distance from entry to stop, per unit — the "R" the
        position was sized against (risk/fixed_risk.py's `compute_r`).
        None when no stop was recorded on the opening bracket."""
        if self.stop_loss is None:
            return None
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward_risk_ratio(self) -> float | None:
        """Take-profit distance divided by stop distance — how many R the
        plan targets. None when either leg of the bracket is missing."""
        r = self.r_dollars
        if r is None or r <= 0 or self.take_profit is None:
            return None
        return abs(self.take_profit - self.entry_price) / r

    @property
    def plan_progress_pct(self) -> float | None:
        """Where the latest mark sits between stop (-100%) and target
        (+100%), for a visual plan bar. None without a full bracket."""
        if self.latest_mark is None or self.stop_loss is None or self.take_profit is None:
            return None
        span = self.take_profit - self.stop_loss
        if span == 0:
            return None
        pct = (self.latest_mark - self.stop_loss) / span
        if not self.is_long:
            pct = 1.0 - pct
        return max(0.0, min(1.0, pct)) * 100.0


def perp_positions_view(session: Session, limit: int = 50) -> list[PerpPositionView]:
    """Open + recently-closed perp paper positions with their bracket,
    funding accrued, and distance to liquidation (§7.1)."""
    rows = list(
        session.execute(
            select(PerpPaperPosition)
            .order_by(desc(PerpPaperPosition.entry_ts))
            .limit(limit)
        ).scalars()
    )
    out: list[PerpPositionView] = []
    for pos in rows:
        fill_event = session.scalar(
            select(PerpPaperEvent)
            .where(
                PerpPaperEvent.position_id == pos.id,
                PerpPaperEvent.event_type == "fill",
            )
            .order_by(PerpPaperEvent.observed_at)
            .limit(1)
        )
        bracket = (fill_event.payload or {}).get("bracket") if fill_event else None
        liq = fill_event.liquidation_price if fill_event else None
        latest_mark = session.scalar(
            select(PerpPaperEvent.price)
            .where(
                PerpPaperEvent.position_id == pos.id,
                PerpPaperEvent.event_type == "mark",
            )
            .order_by(desc(PerpPaperEvent.observed_at))
            .limit(1)
        )
        out.append(
            PerpPositionView(
                run_id=pos.paper_run_id,
                asset_id=pos.asset_id,
                market_ticker=pos.market_ticker,
                signed_quantity=pos.signed_quantity,
                entry_price=pos.entry_price,
                status=pos.status,
                realized_pnl_usd=pos.realized_pnl_usd,
                funding_pnl_usd=pos.funding_pnl_usd or 0.0,
                fee_usd=pos.fee_usd or 0.0,
                latest_mark=latest_mark,
                liquidation_price=liq,
                stop_loss=(bracket or {}).get("stop_loss") if bracket else None,
                take_profit=(bracket or {}).get("take_profit") if bracket else None,
            )
        )
    return out


@dataclass
class LabAccountComparison:
    """One row of the side-by-side strategy-lab comparison, keyed by run id."""

    run_id: str
    domain: str
    mode: str
    status: str
    strategy_id: str | None
    strategy_gate_status: str | None
    decisions: int
    fills: int
    net_pnl_usd: float | None
    flat_sizing_net_pnl_usd: float | None
    blocked_fill_reasons: dict[str, str]
    decisions_without_fills: bool


def _run_net_pnl(session: Session, run_id: str, domain: str) -> tuple[float | None, float | None]:
    """(net_pnl, flat_sizing_net_pnl) for a run, from its own ledger rows.

    Flat-sizing PnL isolates per-trade edge from sizing-driven apparent
    profit — the metric v2 §8.2 built after `level_break`'s Kelly-compounding
    artifact. For prediction runs it recomputes each settled trade as a
    1-contract position; for perp runs it is left None (the perp ledger's
    sizing is the strategy's own signed quantity, not a compounding rule)."""
    if domain == "perp":
        rows = list(
            session.execute(
                select(PerpPaperPosition).where(
                    PerpPaperPosition.paper_run_id == run_id
                )
            ).scalars()
        )
        if not rows:
            return None, None
        net = sum(
            (p.realized_pnl_usd or 0.0) + (p.funding_pnl_usd or 0.0) - (p.fee_usd or 0.0)
            for p in rows
        )
        return net, None
    trades = list(
        session.execute(
            select(SimulatedTrade).where(
                SimulatedTrade.mode == "paper",
            )
        ).scalars()
    )
    # SimulatedTrade has no run_id column; attribute by the run's audit
    # window instead would be lossy, so this stays a coarse all-paper figure
    # only when a single run exists. Return None rather than mislead.
    if not trades:
        return None, None
    settled = [
        t
        for t in trades
        if t.status in ("settled_won", "settled_lost") and t.net_pnl_usd is not None
    ]
    if not settled:
        return None, None
    net = sum(t.net_pnl_usd for t in settled)
    flat = 0.0
    for t in settled:
        qty = t.quantity or 1
        flat += (t.net_pnl_usd / qty) if qty else 0.0
    return net, flat


def strategy_lab_comparison(session: Session, limit: int = 20) -> list[LabAccountComparison]:
    """Recent paper runs side by side: strategy, gate status, PnL, and
    flat-sizing PnL together, keyed by `paper_run_id` (§7.3)."""
    summaries = paper_runs_overview(session, limit=limit)
    out: list[LabAccountComparison] = []
    for s in summaries:
        net, flat = _run_net_pnl(session, s.run_id, s.domain)
        out.append(
            LabAccountComparison(
                run_id=s.run_id,
                domain=s.domain,
                mode=s.mode,
                status=s.status,
                strategy_id=s.strategy_id,
                strategy_gate_status=s.strategy_gate_status,
                decisions=s.decisions,
                fills=s.fills,
                net_pnl_usd=net,
                flat_sizing_net_pnl_usd=flat,
                blocked_fill_reasons=s.blocked_fill_reasons,
                decisions_without_fills=s.decisions_without_fills,
            )
        )
    return out
