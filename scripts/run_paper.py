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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from loguru import logger  # noqa: E402

from kalshi_bot.config.settings import get_settings  # noqa: E402
from kalshi_bot.data.kalshi.client import KalshiPublicClient  # noqa: E402
from kalshi_bot.execution.orchestrator import (  # noqa: E402
    PaperOrchestrator,
    PaperRunConfig,
    PreflightError,
    load_run_events,
    summarize_run,
)
from kalshi_bot.execution.prediction_adapter import (  # noqa: E402
    PredictionPaperAdapter,
    db_settlement_source,
    hold_strategy,
    kalshi_public_quote_source,
)
from kalshi_bot.storage.db import (  # noqa: E402
    create_all_tables,
    get_engine,
    get_session_factory,
)


def _parse_assets(raw: str) -> tuple[str, ...]:
    assets = tuple(a.strip().upper() for a in raw.split(",") if a.strip())
    if not assets:
        raise argparse.ArgumentTypeError("--assets must list at least one symbol")
    return assets


def _build_adapter(domain: str, session_factory, settings):
    if domain == "prediction":
        session = session_factory()
        client = KalshiPublicClient()
        return PredictionPaperAdapter(
            session=session,
            quote_source=kalshi_public_quote_source(client),
            settlement_source=db_settlement_source(session),
            starting_cash_usd=settings.bankroll_total_usd,
            # Strategy selection is still open (design Open Questions); the
            # default records decisions without ever entering. Swap in a real
            # StrategyFn once a candidate is chosen and frozen.
            strategy=hold_strategy,
        )
    raise SystemExit(
        f"--domain {domain} has no adapter wired into scripts/run_paper.py yet; "
        "prediction is the only domain currently runnable from this command."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, choices=("prediction", "perp", "sports"))
    parser.add_argument("--assets", required=True, type=_parse_assets)
    parser.add_argument("--mode", choices=("shadow", "paper"), default="shadow")
    parser.add_argument("--duration", type=float, default=None, help="seconds; omit for Ctrl+C")
    parser.add_argument("--strategy-id", default="unspecified")
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

    adapter = _build_adapter(args.domain, session_factory, settings)
    orchestrator = PaperOrchestrator(
        settings=settings,
        config=config,
        session_factory=session_factory,
        adapter=adapter,
        now_fn=time.time,
        sleep_fn=time.sleep,
        cycle_seconds=args.cycle_interval,
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
