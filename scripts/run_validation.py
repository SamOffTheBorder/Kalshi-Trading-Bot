"""Run the reproducible KXBTC15M validation gate.

This command is intentionally fail-closed.  A checkout without the archived
KXBTC15M/BRTI dataset produces a validation report with three failed arms and
an explicit data-availability reason; it never substitutes another series.
Once the archive is present, the same manifest is the input boundary for the
per-fold evaluator supplied by the backtest owner.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import func, select

from kalshi_bot.backtest.promotion_gate import enforce_paper_promotion
from kalshi_bot.backtest.report import aggregate_reports
from kalshi_bot.config.settings import Settings
from kalshi_bot.storage.db import create_all_tables, get_engine, get_session_factory
from kalshi_bot.storage.models import BRTIObservation, Candle, KalshiMarket
from kalshi_bot.strategy.experiments import deferred_experiments

ARMS = ("settlement_probability", "trend_drift", "trend_control")


def _empty_arm(reason: str) -> dict[str, object]:
    report = enforce_paper_promotion(aggregate_reports([], evidence_class="validation"))
    payload = report.to_dict()
    payload["promotion_reasons"] = (*report.promotion_reasons, reason)
    payload["promotion_status"] = "failed"
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/kalshi_bot.db"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    engine = get_engine(Settings(db_path=args.db))
    create_all_tables(engine)
    session_factory = get_session_factory(engine)
    with session_factory() as session:
        markets = session.scalar(
            select(func.count()).select_from(KalshiMarket).where(
                KalshiMarket.series_ticker == "KXBTC15M"
            )
        ) or 0
        candles = session.scalar(
            select(func.count()).select_from(Candle).where(Candle.series_ticker == "KXBTC15M")
        ) or 0
        brti = session.scalar(select(func.count()).select_from(BRTIObservation)) or 0

    if not markets or not candles or not brti:
        reason = (
            "NO-GO: archived KXBTC15M validation data is incomplete "
            f"(markets={markets}, candles={candles}, brti={brti}); "
            "run scripts/fetch_historical.py and a deliberate BRTI capture/import first"
        )
        result = {
            "instrument": "KXBTC15M",
            "evidence_class": "validation",
            "dataset": {"markets": markets, "candles": candles, "brti": brti},
            "arms": {arm: _empty_arm(reason) for arm in ARMS},
            "incremental_trend_vs_control": None,
            "deferred_experiments": [e.__dict__ for e in deferred_experiments()],
            "verdict": "FAIL",
            "failure_order": [
                "funding carry: not evaluated; perp/event ledger is separate",
                "weather: not applicable to KXBTC15M",
                "park: validation parked until causal BRTI archive exists",
            ],
        }
    else:
        raise RuntimeError(
            "KXBTC15M data exists, but the engine-side BRTI/sizer injection hook is not "
            "available in this lane; see scratchpad/codex-notes-for-claude.md"
        )

    encoded = json.dumps(result, indent=2, sort_keys=True, default=str)
    verdict = "FAIL" if result["verdict"] == "FAIL" else "PASS"
    print(f"KXBTC15M VALIDATION: {verdict}")
    print(encoded)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
