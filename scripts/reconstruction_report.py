"""Print reconstruction-error level error, resolution agreement, or
`unmeasured` for a window (brti-constituent-history §6).

Reads captured BRTI from `brti_observations` and the synthetic proxy from
`reconstructed_index_observations`, then reports the divergence at the
KXBTC15M resolution timescale. Never emits a passing status for an
unmeasured reconstruction.

Usage:
  uv run python scripts/reconstruction_report.py \
      --start 2026-01-01T00:00:00 --end 2026-01-01T01:00:00
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kalshi_bot.config.settings import Settings
from kalshi_bot.data.reconstruction_error import IndexPoint, measure_reconstruction_error
from kalshi_bot.signals.settlement_window import DEFAULT_WINDOW_SECONDS
from kalshi_bot.storage.db import create_all_tables, get_engine, get_session_factory
from kalshi_bot.storage.models import BRTIObservation, ReconstructedIndexObservation

CONTRACT_SECONDS = 15 * 60


def _parse_ts(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp())


def _contract_windows(start_ts: int, end_ts: int) -> tuple[tuple[int, int], ...]:
    windows = []
    open_ts = start_ts - (start_ts % CONTRACT_SECONDS)
    while open_ts + CONTRACT_SECONDS <= end_ts:
        windows.append((open_ts, open_ts + CONTRACT_SECONDS))
        open_ts += CONTRACT_SECONDS
    return tuple(windows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--target-index", default="BRTI")
    parser.add_argument("--db", type=Path, default=Path("data/kalshi_bot.db"))
    args = parser.parse_args()

    start_ts, end_ts = _parse_ts(args.start), _parse_ts(args.end)
    if start_ts >= end_ts:
        raise SystemExit("--start must precede --end")

    engine = get_engine(Settings(db_path=args.db))
    create_all_tables(engine)
    with get_session_factory(engine)() as session:
        captured_rows = (
            session.query(BRTIObservation)
            .filter(
                BRTIObservation.observed_at >= start_ts, BRTIObservation.observed_at < end_ts
            )
            .all()
        )
        reconstructed_rows = (
            session.query(ReconstructedIndexObservation)
            .filter(
                ReconstructedIndexObservation.target_index == args.target_index,
                ReconstructedIndexObservation.observed_at >= start_ts,
                ReconstructedIndexObservation.observed_at < end_ts,
            )
            .all()
        )

    captured = tuple(
        IndexPoint(observed_at=row.observed_at, value=float(row.value_dollars))
        for row in captured_rows
    )
    reconstructed = tuple(
        IndexPoint(observed_at=row.observed_at, value=float(row.value_dollars))
        for row in reconstructed_rows
    )

    report = measure_reconstruction_error(
        captured,
        reconstructed,
        contract_windows=_contract_windows(start_ts, end_ts),
        window_seconds=DEFAULT_WINDOW_SECONDS,
    )
    print(
        {
            "target_index": args.target_index,
            "captured_rows": len(captured),
            "reconstructed_rows": len(reconstructed),
            **report.as_dict(),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
