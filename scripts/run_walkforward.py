"""Print an embargoed walk-forward plan for a validation evaluator.

The evaluator is deliberately supplied by the caller/library: each fold must
construct its own strategy, broker, cash ledger, and guards.  This command is
useful for checking the exact split boundaries before running a strategy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kalshi_bot.backtest.walkforward import rolling_folds


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-ts", type=int, required=True)
    parser.add_argument("--end-ts", type=int, required=True)
    parser.add_argument("--train-days", type=int, required=True)
    parser.add_argument("--test-days", type=int, required=True)
    parser.add_argument("--embargo-hours", type=int, default=24)
    parser.add_argument("--step-days", type=int, default=None)
    args = parser.parse_args()
    folds = rolling_folds(
        start_ts=args.start_ts, end_ts=args.end_ts,
        train_seconds=args.train_days * 86_400,
        test_seconds=args.test_days * 86_400,
        embargo_seconds=args.embargo_hours * 3_600,
        step_seconds=None if args.step_days is None else args.step_days * 86_400,
    )
    print(json.dumps([fold.__dict__ for fold in folds], indent=2))


if __name__ == "__main__":
    main()
