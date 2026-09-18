"""Foreground, registry-driven paper-run command (multi-venue-paper-trading §8.3).

    python scripts/run_paper.py --domain prediction --assets BTC,ETH --duration 900

Explicit `--domain` (`prediction` | `perp` | `sports`), an explicit subset of
the active crypto universe, and a bounded `--duration` (omit to run until
Ctrl+C). Safe defaults: `--mode shadow` unless `--mode paper` is passed, and
`--mode paper` still creates fills only for a `paper`-lifecycle asset with a
frozen admission report.

No scheduler, no daemon, no auto-restart, and no live order path: the
`PaperExecutionGuard` refuses a production-authenticated or non-paper
configuration during preflight, and only the simulated adapter surface is
ever called. SIGINT/SIGTERM stop the run cleanly with a final heartbeat and
reconciliation status persisted.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from loguru import logger  # noqa: E402

from kalshi_bot.config.settings import get_settings  # noqa: E402
from kalshi_bot.data.kalshi.client import KalshiPublicClient  # noqa: E402
from kalshi_bot.data.sports.validation import (  # noqa: E402
    FeasibilityReport,
    evaluate_sports_paper_admission,
)
from kalshi_bot.execution.orchestrator import (  # noqa: E402
    PaperOrchestrator,
    PaperRunConfig,
    PreflightError,
    load_run_events,
    resolve_strategy_id,
    summarize_run,
)
from kalshi_bot.execution.perp_adapter import (  # noqa: E402
    PerpPaperDomainAdapter,
    db_perp_coverage_reader,
    db_perp_discovery_reader,
    db_perp_market_reader,
    hold_perp_strategy,
)
from kalshi_bot.execution.prediction_adapter import (  # noqa: E402
    PredictionPaperAdapter,
    db_settlement_source,
    kalshi_public_quote_source,
)
from kalshi_bot.execution.sports_paper import (  # noqa: E402
    SportsCandidate,
    SportsPaperAdapter,
    db_sports_settlement_source,
    hold_sports_strategy,
)
from kalshi_bot.storage.db import (  # noqa: E402
    create_all_tables,
    get_engine,
    get_session_factory,
)
from kalshi_bot.strategy.registry import build_strategy  # noqa: E402


def _parse_assets(raw: str) -> tuple[str, ...]:
    assets = tuple(a.strip().upper() for a in raw.split(",") if a.strip())
    if not assets:
        raise argparse.ArgumentTypeError("--assets must list at least one symbol")
    return assets


def _build_adapter(domain: str, session_factory, settings, *, strategy_id: str, run_id: str):
    if domain == "prediction":
        session = session_factory()
        client = KalshiPublicClient()
        # The registry strategy — a `StrategyProtocol` object — is driven
        # through `PredictionPaperAdapter`'s causal `StrategyContext` builder
        # (strategy-lab-multi-account §2). An unknown id was already refused
        # at preflight; `resolve_strategy_id` maps the legacy sentinels to
        # the hold default.
        strategy = build_strategy(resolve_strategy_id(strategy_id))
        return PredictionPaperAdapter(
            session=session,
            quote_source=kalshi_public_quote_source(client),
            settlement_source=db_settlement_source(session),
            starting_cash_usd=settings.bankroll_total_usd,
            strategy=strategy,
        )
    if domain == "perp":
        session = session_factory()
        # DB-backed read-only sources over captured PerpMarkObservation /
        # PerpFundingObservation / DiscoveryResult rows — no execution client,
        # no order endpoint (strategy-lab-multi-account §4.6). The directional
        # strategy defaults to hold: the registry holds only single-instrument
        # `StrategyProtocol` strategies, and the two-leg funding-carry path is
        # driven separately (§5). A directional perp strategy is out of this
        # change's registry scope.
        return PerpPaperDomainAdapter(
            session=session,
            paper_run_id=run_id,
            market_reader=db_perp_market_reader(session),
            coverage_reader=db_perp_coverage_reader(session),
            discovery_reader=db_perp_discovery_reader(session),
            collateral_usd=settings.bankroll_total_usd,
            strategy=hold_perp_strategy,
        )
    if domain == "sports":
        session = session_factory()
        # The CLI wiring intentionally constructs a gated adapter even when
        # no persisted feasibility report exists yet.  The adapter's
        # admission wall records `research_not_promising` on each tick and
        # cannot produce a fill in that state.
        report = FeasibilityReport(
            outcome="insufficient_data",
            sample_count=0,
            opportunity_count=0,
            eligible_fills=0,
            rejected_fills=0,
            net_pnl_usd=0.0,
            max_drawdown_usd=0.0,
            concentration=0.0,
        )
        admission = evaluate_sports_paper_admission(
            report,
            rules_verified=False,
            provider_evidence=False,
            fresh_data=False,
            liquid_quote=False,
            strategy_version=None,
            operator_acknowledged=False,
        )
        return SportsPaperAdapter(
            session=session,
            candidate=SportsCandidate(
                sport="all",
                market_class="pre_game_moneyline",
                strategy_version="cli-unconfigured",
                execution_assumptions_hash="cli-unconfigured",
            ),
            admission=admission,
            market_source=lambda _now: None,
            evidence_source=lambda _ticker, _now: (),
            settlement_source=db_sports_settlement_source(session),
            starting_cash_usd=settings.bankroll_total_usd,
            strategy=hold_sports_strategy,
        )
    raise SystemExit(
        f"--domain {domain} has no adapter wired into scripts/run_paper.py yet; "
        "prediction, perp, and sports are runnable from this command."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, choices=("prediction", "perp", "sports"))
    parser.add_argument("--assets", required=True, type=_parse_assets)
    parser.add_argument("--mode", choices=("shadow", "paper"), default="shadow")
    parser.add_argument("--duration", type=float, default=None, help="seconds; omit for Ctrl+C")
    parser.add_argument(
        "--strategy",
        dest="strategy_id",
        default="unspecified",
        help="registered strategy id (see strategy/registry.py); omit for the "
        "hold default. An unknown id is refused at preflight.",
    )
    parser.add_argument(
        "--strategy-id",
        dest="strategy_id",
        help="deprecated alias for --strategy",
    )
    parser.add_argument("--config-id", default="unspecified")
    parser.add_argument("--report-id", default=None)
    parser.add_argument("--cycle-interval", type=float, default=5.0)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    if args.db is not None:
        settings = settings.model_copy(update={"db_path": args.db})

    if not settings.paper_trading:
        raise SystemExit("PAPER_TRADING is false; this command only runs paper/shadow mode.")

    engine = get_engine(settings)
    create_all_tables(engine)
    session_factory = get_session_factory(engine)

    config = PaperRunConfig(
        domain=args.domain,
        assets=args.assets,
        mode=args.mode,
        duration_seconds=args.duration,
        strategy_id=args.strategy_id,
        config_id=args.config_id,
        report_id=args.report_id,
    )

    # The perp adapter persists positions against `paper_run_id`, so the id
    # is generated here and shared with both the adapter and the orchestrator
    # rather than left to the orchestrator's internal default.
    run_id = uuid.uuid4().hex
    adapter = _build_adapter(
        args.domain, session_factory, settings,
        strategy_id=args.strategy_id, run_id=run_id,
    )
    orchestrator = PaperOrchestrator(
        settings=settings,
        config=config,
        session_factory=session_factory,
        adapter=adapter,
        now_fn=time.time,
        sleep_fn=time.sleep,
        cycle_seconds=args.cycle_interval,
        run_id=run_id,
    )

    try:
        run_id = orchestrator.run()
    except PreflightError as exc:
        logger.error("Preflight refused the run: {}", exc)
        return 2

    with session_factory() as session:
        events = load_run_events(session, run_id)
    logger.info("Paper run {} finished: {}", run_id, summarize_run(events))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
