"""Run a research-only sports feasibility report from JSONL observations.

The input is explicit and point-in-time: one JSON object per line with the
fields of ``SportsObservation``. This command writes a report only; it has no
broker or order-placement dependency.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kalshi_bot.data.sports.validation import SportsObservation, feasibility_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--holdout-ts", type=int, required=True)
    parser.add_argument("--min-sample-size", type=int, default=100)
    parser.add_argument("--slippage-cents", type=float, default=0.0)
    parser.add_argument("--candidate-kind", default="market-baseline")
    parser.add_argument("--feature-version", action="append", default=[])
    parser.add_argument("--evidence-hash", action="append", default=[])
    parser.add_argument("--model-meta", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    observations = [
        SportsObservation(**json.loads(line))
        for line in args.input.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report = feasibility_report(
        observations,
        holdout_ts=args.holdout_ts,
        min_sample_size=args.min_sample_size,
        slippage_cents=args.slippage_cents,
        candidate_kind=args.candidate_kind,
        feature_versions=args.feature_version,
        evidence_hashes=args.evidence_hash,
        model_metadata=json.loads(args.model_meta.read_text(encoding="utf-8"))
        if args.model_meta
        else None,
    )
    encoded = json.dumps(report.as_dict(), indent=2, sort_keys=True)
    print(encoded)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
