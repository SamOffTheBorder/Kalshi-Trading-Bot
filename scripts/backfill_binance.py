"""Bulk, resumable Binance monthly-archive backfill (multi-venue §2 data lake).

``import_binance_data.py`` imports exactly one asset / market-type / month.
This driver sweeps a month range across the whole active crypto universe so
the primary source can be filled in one foreground session instead of dozens
of hand-typed invocations.

Read-only against Binance's public archive. It never constructs an exchange
client capable of submitting an order, and it never fabricates a bar: a month
Binance has not published yet is reported as ``missing`` and skipped, not
forward-filled from its neighbours.

Resumability is inherited from the importer, which de-duplicates on
``(source, venue, native_symbol, market_type, period_minutes, open_ts,
parser_version)``. Re-running the same range is therefore idempotent and cheap.
A month is skipped without a network call when its archive is already cached
*and* its bars are already in the database, so a download that failed to import
is retried rather than mistaken for finished work. ``--force`` re-downloads.

Usage:
  uv run python scripts/backfill_binance.py --start 2025-01 --end 2026-08
  uv run python scripts/backfill_binance.py --start 2026-01 --end 2026-08 \
      --asset BTC --asset ETH --market-type spot
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from kalshi_bot.data.external_sources import (  # noqa: E402
    ACTIVE_CRYPTO_ASSETS,
    binance_instrument,
)

IMPORTER = REPO_ROOT / "scripts" / "import_binance_data.py"

# The importer requires the timestamp unit to be stated rather than sniffed, so
# it is declared here per market type and asserted after import — a wrong unit
# stores epochs millennia out instead of failing, so it is checked, not trusted.
# Verified against the real 2026-07 archives:
#   spot  BTCUSDT-1m-2026-07: open_time 1782864000000000  -> microseconds
#   perp  BTCUSDT-1m-2026-07: open_time 1782864000000     -> milliseconds
# The futures archive also ships a CSV header row; the spot one does not.
ARCHIVE_TIMESTAMP_UNIT = {"spot": "us", "perp": "ms"}

# `normalize_klines` stores open_ts in epoch MILLISECONDS. An open_ts outside
# this window (roughly 2014-2049) means the declared unit was wrong.
SANE_EPOCH_MS_RANGE = (1_400_000_000_000, 2_500_000_000_000)


def _months(start: str, end: str) -> list[tuple[int, int]]:
    def parse(value: str) -> tuple[int, int]:
        try:
            year, month = value.split("-")
            year_i, month_i = int(year), int(month)
        except ValueError as exc:
            raise SystemExit(f"expected YYYY-MM, got {value!r}") from exc
        if not 1 <= month_i <= 12:
            raise SystemExit(f"month out of range in {value!r}")
        return year_i, month_i

    first, last = parse(start), parse(end)
    if first > last:
        raise SystemExit("--start must not be after --end")
    out: list[tuple[int, int]] = []
    year, month = first
    while (year, month) <= last:
        out.append((year, month))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def _month_bounds_ms(year: int, month: int) -> tuple[int, int]:
    from datetime import UTC, datetime

    start = datetime(year, month, 1, tzinfo=UTC)
    end = datetime(year + (month == 12), (month % 12) + 1, 1, tzinfo=UTC)
    return int(start.timestamp()) * 1_000, int(end.timestamp()) * 1_000


def _already_imported(
    db: Path, native_symbol: str, market_type: str, year: int, month: int
) -> bool:
    """True when this instrument-month already has normalized bars stored."""
    import sqlite3

    if not db.exists():
        return False
    low, high = _month_bounds_ms(year, month)
    with sqlite3.connect(db) as connection:
        count = connection.execute(
            "select count(*) from normalized_market_bars "
            "where source='binance' and native_symbol=? and market_type=? "
            "and open_ts >= ? and open_ts < ?",
            (native_symbol, market_type, low, high),
        ).fetchone()[0]
    return count > 0


def _assert_sane_timestamps(db: Path) -> None:
    """Fail loudly if any imported bar has an implausible epoch.

    A mis-declared timestamp unit does not raise — it stores open_ts values
    millions of years out. Nothing downstream would notice, so the invariant
    is checked here rather than assumed.
    """
    import sqlite3

    low, high = SANE_EPOCH_MS_RANGE
    with sqlite3.connect(db) as connection:
        bad = connection.execute(
            "select count(*) from normalized_market_bars where open_ts < ? or open_ts > ?",
            (low, high),
        ).fetchone()[0]
    if bad:
        raise SystemExit(
            f"ABORT: {bad} normalized_market_bars rows have an out-of-range open_ts. "
            "The declared timestamp unit is wrong; purge those rows before continuing."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="first month, YYYY-MM")
    parser.add_argument("--end", required=True, help="last month, YYYY-MM (inclusive)")
    parser.add_argument(
        "--asset",
        action="append",
        choices=sorted(ACTIVE_CRYPTO_ASSETS),
        help="repeatable; defaults to every active crypto asset",
    )
    parser.add_argument(
        "--market-type",
        action="append",
        choices=("spot", "perp"),
        help="repeatable; defaults to both spot and perp",
    )
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--db", type=Path, default=Path("data/kalshi_bot.db"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/external"))
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download months whose artifact is already cached locally",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.5,
        help="seconds to wait between archive downloads (politeness)",
    )
    args = parser.parse_args()

    assets = args.asset or sorted(ACTIVE_CRYPTO_ASSETS)
    market_types = args.market_type or ["spot", "perp"]
    months = _months(args.start, args.end)

    jobs = [(a, m, y, mo) for a in assets for m in market_types for (y, mo) in months]
    print(
        f"backfill: {len(assets)} asset(s) x {len(market_types)} market type(s) "
        f"x {len(months)} month(s) = {len(jobs)} archives\n"
    )

    imported = skipped = missing = failed = 0
    for index, (asset, market_type, year, month) in enumerate(jobs, start=1):
        label = f"{asset}/{market_type}/{year:04d}-{month:02d}"
        prefix = f"[{index}/{len(jobs)}] {label}"

        # Spot and USD-M perp share a native symbol (BTCUSDT), so the market
        # type must be part of the cache path or a perp month would silently
        # match the spot archive and be skipped.
        instrument = binance_instrument(asset, market_type)
        raw_dir = args.raw_dir / market_type
        cached = raw_dir / f"{instrument.native_symbol}-{args.interval}-{year:04d}-{month:02d}.zip"
        # A cached zip alone is not proof the month is imported -- an earlier
        # run may have downloaded it and then failed to normalize or insert.
        # Skip only when the bars are actually in the database.
        if cached.exists() and not args.force and _already_imported(
            args.db, instrument.native_symbol, market_type, year, month
        ):
            print(f"{prefix}: already imported, skipping")
            skipped += 1
            continue

        completed = subprocess.run(
            [
                sys.executable,
                str(IMPORTER),
                "--asset", asset,
                "--market-type", market_type,
                "--interval", args.interval,
                "--year", str(year),
                "--month", str(month),
                "--timestamp-unit", ARCHIVE_TIMESTAMP_UNIT[market_type],
                "--db", str(args.db),
                "--raw-dir", str(raw_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        stream = (completed.stdout or "") + (completed.stderr or "")
        if completed.returncode == 0:
            tail = completed.stdout.strip().splitlines()
            print(f"{prefix}: {tail[-1] if tail else 'ok'}")
            imported += 1
        elif "404" in stream:
            # Binance has not published this month for this instrument. That is
            # a real absence, recorded as such and never filled from neighbours.
            print(f"{prefix}: not published by Binance, skipping")
            missing += 1
        else:
            print(f"{prefix}: FAILED\n{stream.strip()[-1200:]}")
            failed += 1

        if args.pause:
            time.sleep(args.pause)

    _assert_sane_timestamps(args.db)
    print(
        f"\ndone: {imported} imported, {skipped} already cached, "
        f"{missing} not published, {failed} failed"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
