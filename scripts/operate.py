"""Foreground operator command hub (multi-venue-paper-trading §12.3).

    python scripts/operate.py <command> [args...]

Commands:
  discover  [--asset BTC ...]     run Kalshi crypto-series discovery
  import    [script args...]      bounded Binance archive import
  validate  [script args...]      frozen out-of-sample validation run
  manifest  [script args...]      validation run + freeze a dataset manifest
  backtest  [script args...]      reproducible backtest
  shadow    --domain D --assets X run a shadow paper run (records, no fills)
  paper     --domain D --assets X run a paper run (fills only for admitted scope)
  health    <paper_run_id>        print the run-health + reconciliation report
  reconcile <paper_run_id>        list unresolved reconciliation conditions
  halt      [reason...]           set the durable global emergency halt
  resume    <operator> [note...]  clear the halt (refuses if unreconciled)

Every invocation writes a redacted effective-config audit record to
`paper_audit_events` under a per-day `ops` run. No scheduler, no daemon.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from kalshi_bot.config.settings import get_settings  # noqa: E402
from kalshi_bot.execution.operator_cli import (  # noqa: E402
    ALL_COMMANDS,
    OperatorCommandError,
    OperatorConsole,
)
from kalshi_bot.storage.db import (  # noqa: E402
    create_all_tables,
    get_engine,
    get_session_factory,
)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    command, args = argv[0], argv[1:]
    if command not in ALL_COMMANDS:
        print(f"unknown command {command!r}; known: {', '.join(ALL_COMMANDS)}", file=sys.stderr)
        return 2

    settings = get_settings()
    engine = get_engine(settings)
    create_all_tables(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        console = OperatorConsole(session=session, settings=settings)
        try:
            code = console.run(command, args)
        except OperatorCommandError as exc:
            session.commit()  # keep the rejection audit row
            print(str(exc), file=sys.stderr)
            return 2
        session.commit()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
