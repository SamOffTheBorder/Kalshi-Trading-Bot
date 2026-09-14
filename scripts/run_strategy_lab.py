"""Foreground multi-account paper lab (strategy-lab-multi-account §6).

Starts N concurrent paper "accounts" from a declarative JSON spec — each with
its own strategy, config id, asset set, bankroll, mode, and duration — and
runs them side by side so an operator can compare strategies on the same live
data. Every account is a full `PaperOrchestrator` run with its own
`paper_run_id`; positions, fills, audit events, and capital are attributable
to exactly one account and no account's sizing observes another's (§6.2 —
each `PredictionPaperAdapter` builds its own `PaperBroker` with its own
`starting_cash_usd`).

Foreground only. No scheduler, no daemon, no auto-restart (§6.5, standing O1).
One Ctrl+C forwards a clean stop to every account and waits for each to
persist its final heartbeat and reconciliation status.

Spec file (JSON):

    {
      "poll_interval_seconds": 15,
      "accounts": [
        {"name": "scalp-A", "domain": "prediction", "strategy": "trend_scalp",
         "assets": ["BTC"], "bankroll_usd": 250, "mode": "shadow",
         "duration_seconds": 3600, "config_id": "trend_scalp-default"},
        {"name": "scalp-B", "domain": "prediction", "strategy": "level_break",
         "assets": ["BTC", "ETH"], "bankroll_usd": 250, "mode": "shadow"}
      ]
    }

`poll_interval_seconds` is the per-account cycle cadence — keep it >= 10s so
several accounts polling Kalshi's public endpoints do not defeat the client's
existing 429 backoff (§6.3). `MAX_ACCOUNTS` caps the fan-out.

    uv run python scripts/run_strategy_lab.py --spec lab.json
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
from dataclasses import dataclass
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
    resolve_strategy_id,
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
from kalshi_bot.storage.db import (  # noqa: E402
    create_all_tables,
    get_engine,
    get_session_factory,
)
from kalshi_bot.strategy.registry import build_strategy  # noqa: E402

MAX_ACCOUNTS = 8
MIN_POLL_INTERVAL_SECONDS = 10.0


@dataclass(frozen=True)
class AccountSpec:
    name: str
    domain: str
    strategy_id: str
    assets: tuple[str, ...]
    bankroll_usd: float
    mode: str
    duration_seconds: float | None
    config_id: str

    @staticmethod
    def from_dict(raw: dict) -> AccountSpec:
        assets = tuple(a.strip().upper() for a in raw.get("assets", []) if a.strip())
        if not assets:
            raise ValueError(f"account {raw.get('name')!r}: assets must be non-empty")
        return AccountSpec(
            name=str(raw["name"]),
            domain=str(raw.get("domain", "prediction")),
            strategy_id=str(raw.get("strategy", "unspecified")),
            assets=assets,
            bankroll_usd=float(raw.get("bankroll_usd", 0.0)) or _default_bankroll(),
            mode=str(raw.get("mode", "shadow")),
            duration_seconds=(
                float(raw["duration_seconds"])
                if raw.get("duration_seconds") is not None
                else None
            ),
            config_id=str(raw.get("config_id", "unspecified")),
        )


def _default_bankroll() -> float:
    return float(get_settings().bankroll_total_usd)


@dataclass
class AccountRun:
    spec: AccountSpec
    run_id: str
    orchestrator: PaperOrchestrator
    thread: threading.Thread
    error: BaseException | None = None


def _build_adapter(spec: AccountSpec, session_factory, run_id: str):
    if spec.domain == "prediction":
        session = session_factory()
        client = KalshiPublicClient()
        strategy = build_strategy(resolve_strategy_id(spec.strategy_id))
        return PredictionPaperAdapter(
            session=session,
            quote_source=kalshi_public_quote_source(client),
            settlement_source=db_settlement_source(session),
            starting_cash_usd=spec.bankroll_usd,
            strategy=strategy,
        )
    if spec.domain == "perp":
        session = session_factory()
        return PerpPaperDomainAdapter(
            session=session,
            paper_run_id=run_id,
            market_reader=db_perp_market_reader(session),
            coverage_reader=db_perp_coverage_reader(session),
            discovery_reader=db_perp_discovery_reader(session),
            collateral_usd=spec.bankroll_usd,
            strategy=hold_perp_strategy,
        )
    raise SystemExit(
        f"account {spec.name!r}: domain {spec.domain!r} is not runnable "
        "(prediction | perp)"
    )


def _start_account(
    spec: AccountSpec, settings, session_factory, *, poll_interval: float
) -> AccountRun:
    run_id = uuid.uuid4().hex
    adapter = _build_adapter(spec, session_factory, run_id)
    config = PaperRunConfig(
        domain=spec.domain,
        assets=spec.assets,
        mode=spec.mode,
        duration_seconds=spec.duration_seconds,
        strategy_id=spec.strategy_id,
        config_id=spec.config_id,
    )
    orch = PaperOrchestrator(
        settings=settings,
        config=config,
        session_factory=session_factory,
        adapter=adapter,
        now_fn=time.time,
        sleep_fn=time.sleep,
        cycle_seconds=poll_interval,
        run_id=run_id,
    )

    account = AccountRun(spec=spec, run_id=run_id, orchestrator=orch, thread=None)  # type: ignore[arg-type]

    def _run() -> None:
        try:
            orch.run()
        except PreflightError as exc:
            account.error = exc
            logger.error("[{}] preflight refused: {}", spec.name, exc)
        except BaseException as exc:  # surfaced on the account, never swallowed
            account.error = exc
            logger.exception("[{}] crashed", spec.name)

    thread = threading.Thread(target=_run, name=f"lab-{spec.name}", daemon=True)
    account.thread = thread
    thread.start()
    logger.info(
        "[{}] started run {} — {} {} bankroll ${:.0f} mode={}",
        spec.name, run_id, spec.domain, ",".join(spec.assets),
        spec.bankroll_usd, spec.mode,
    )
    return account


def _load_spec(path: Path) -> tuple[list[AccountSpec], float]:
    raw = json.loads(path.read_text())
    poll_interval = float(raw.get("poll_interval_seconds", MIN_POLL_INTERVAL_SECONDS))
    if poll_interval < MIN_POLL_INTERVAL_SECONDS:
        logger.warning(
            "poll_interval_seconds {} is below the {}s floor; raising it so "
            "concurrent accounts do not defeat the 429 backoff",
            poll_interval, MIN_POLL_INTERVAL_SECONDS,
        )
        poll_interval = MIN_POLL_INTERVAL_SECONDS
    accounts = [AccountSpec.from_dict(a) for a in raw.get("accounts", [])]
    if not accounts:
        raise SystemExit("spec has no accounts")
    if len(accounts) > MAX_ACCOUNTS:
        raise SystemExit(
            f"{len(accounts)} accounts exceeds MAX_ACCOUNTS={MAX_ACCOUNTS}"
        )
    names = [a.name for a in accounts]
    if len(set(names)) != len(names):
        raise SystemExit("account names must be unique")
    return accounts, poll_interval


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="JSON spec file")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    if args.db is not None:
        settings = settings.model_copy(update={"db_path": args.db})
    if not settings.paper_trading:
        raise SystemExit("PAPER_TRADING is false; this command only runs paper/shadow mode.")

    specs, poll_interval = _load_spec(args.spec)

    engine = get_engine(settings)
    create_all_tables(engine)
    session_factory = get_session_factory(engine)

    accounts: list[AccountRun] = []
    for spec in specs:
        accounts.append(
            _start_account(spec, settings, session_factory, poll_interval=poll_interval)
        )

    logger.info(
        "{} account(s) running at a {:.0f}s cadence. Ctrl+C stops all cleanly.",
        len(accounts), poll_interval,
    )

    try:
        while any(a.thread.is_alive() for a in accounts):
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("stop requested — forwarding to {} account(s)", len(accounts))
        for a in accounts:
            a.orchestrator.request_stop()
        for a in accounts:
            a.thread.join(timeout=30.0)

    failed = [a for a in accounts if a.error is not None]
    for a in accounts:
        state = "ERROR" if a.error is not None else "done"
        logger.info("[{}] {} — run {}", a.spec.name, state, a.run_id)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
