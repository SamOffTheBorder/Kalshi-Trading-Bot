"""Foreground-only sports flow/evidence research command.

Reads captured JSONL fixtures, computes causal anonymous-flow features, and
optionally reviews already captured evidence with local Ollama. It never
schedules, restarts, contacts a broker, or places orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kalshi_bot.ai.sports_research import LocalOllamaEvidenceReviewer
from kalshi_bot.data.sports.evidence import EvidenceCard
from kalshi_bot.data.sports.flow import calculate_flow_features


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-ticker", required=True)
    parser.add_argument("--decision-ts", type=int, required=True)
    parser.add_argument("--trades", type=Path, required=True)
    parser.add_argument("--books", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--review-local", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    feature = calculate_flow_features(
        _jsonl(args.trades),
        _jsonl(args.books),
        market_ticker=args.market_ticker,
        decision_ts=args.decision_ts,
    )
    payload = {
        "flow_feature": feature.as_dict(),
        "copy_trading": "copy_trading_unsupported",
        "execution_enabled": False,
    }
    if args.evidence:
        cards = [
            EvidenceCard(**json.loads(line))
            for line in args.evidence.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        payload["evidence_count"] = len(cards)
        payload["evidence_hashes"] = [c.raw_content_hash for c in cards]
        if args.review_local:
            reviewer = LocalOllamaEvidenceReviewer()
            try:
                payload["local_review"] = reviewer.review(
                    market_ticker=args.market_ticker, cards=cards, decision_ts=args.decision_ts
                ).__dict__
            finally:
                reviewer.close()
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
