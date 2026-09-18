"""Run the reproducible KXBTC15M validation gate.

Thin CLI over `kalshi_bot.backtest.validation_run`. Intentionally fail-closed:
a checkout without the archived KXBTC15M / BRTI dataset (or one too short for
three walk-forward folds) produces a report whose arms all FAIL with an
explicit data-availability reason; it never substitutes another series.

Once the archive is present, `run_validation_arms` runs every strategy arm
through the causal engine with fixed-risk sizing and prior-fold-only isotonic
calibration, then applies the enforced promotion gate. Deterministic given a
fixed archive.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kalshi_bot.backtest.validation_run import (
    DEFAULT_TEST_SECONDS,
    DEFAULT_TRAIN_SECONDS,
    run_validation_arms,
)
from kalshi_bot.config.settings import Settings
from kalshi_bot.storage.db import (
    create_all_tables,
    get_engine,
    get_session_factory,
)
from kalshi_bot.strategy.experiments import deferred_experiments


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/kalshi_bot.db"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--train-days", type=int, default=None, help="override the 28-day training window"
    )
    parser.add_argument(
        "--test-days", type=int, default=None, help="override the 14-day test-fold width"
    )
    args = parser.parse_args()

    engine = get_engine(Settings(db_path=args.db))
    create_all_tables(engine)
    session_factory = get_session_factory(engine)

    result = run_validation_arms(
        session_factory,
        train_seconds=(
            args.train_days * 86_400 if args.train_days is not None else DEFAULT_TRAIN_SECONDS
        ),
        test_seconds=(
            args.test_days * 86_400 if args.test_days is not None else DEFAULT_TEST_SECONDS
        ),
    )
    result["deferred_experiments"] = [e.__dict__ for e in deferred_experiments()]
    result.setdefault(
        "failure_order",
        [
            "funding carry: not evaluated; perp/event ledger is separate",
            "weather: not applicable to KXBTC15M",
            "park: an acceptable, expected outcome (v2 plan §8.5)",
        ],
    )

    encoded = json.dumps(result, indent=2, sort_keys=True, default=str)
    print(f"KXBTC15M VALIDATION: {result['verdict']}")
    print(encoded)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
