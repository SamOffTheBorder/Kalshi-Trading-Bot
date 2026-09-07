"""Test whether Coinbase 15-minute returns predict the next Kalshi-style direction.

The label is ``close[t + 1] >= close[t]``, matching an up/down 15-minute
event's direction. This is a feasibility study, not a promotion backtest: it
has no Kalshi executable quotes, fills, BRTI settlement readings, or costs.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import httpx
from scipy.stats import binomtest

COINBASE_URL = "https://api.exchange.coinbase.com"
BAR_SECONDS = 15 * 60
MAX_BARS = 300


def fetch_coinbase_15m(symbol: str, days: int) -> list[tuple[int, float]]:
    """Fetch deduplicated, completed 15-minute closes from Coinbase Exchange."""
    end = int(time.time() // BAR_SECONDS * BAR_SECONDS)
    start = end - days * 24 * 60 * 60
    closes: dict[int, float] = {}
    with httpx.Client(base_url=COINBASE_URL, timeout=20) as client:
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + MAX_BARS * BAR_SECONDS, end)
            response = client.get(
                f"/products/{symbol}/candles",
                params={"granularity": BAR_SECONDS, "start": cursor, "end": chunk_end},
            )
            response.raise_for_status()
            for row in response.json():
                timestamp, _low, _high, _open, close, _volume = row
                timestamp = int(timestamp)
                if start <= timestamp < end:
                    closes[timestamp] = float(close)
            cursor = chunk_end
            time.sleep(0.12)
    return sorted(closes.items())


def _wilson_interval(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return 0.0, 1.0
    p = wins / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return centre - spread, centre + spread


def study(closes: list[tuple[int, float]]) -> dict:
    """Evaluate continuation/reversal of the prior completed 15-minute bar."""
    continuation_correct = reversal_correct = comparable = gaps = 0
    for (t0, p0), (t1, p1), (t2, p2) in zip(closes, closes[1:], closes[2:], strict=False):
        if t1 - t0 != BAR_SECONDS or t2 - t1 != BAR_SECONDS:
            gaps += 1
            continue
        prior_up = p1 >= p0
        next_up = p2 >= p1
        comparable += 1
        continuation_correct += prior_up == next_up
        reversal_correct += prior_up != next_up

    def metrics(wins: int) -> dict:
        accuracy = wins / comparable if comparable else 0.0
        lower, upper = _wilson_interval(wins, comparable)
        return {
            "wins": wins,
            "trades": comparable,
            "accuracy": accuracy,
            "wilson_95_ci": [lower, upper],
            "two_sided_binomial_p": binomtest(wins, comparable, 0.5).pvalue if comparable else None,
            "signal": lower > 0.5,
        }

    return {
        "completed_bars": len(closes),
        "gap_pairs_excluded": gaps,
        "continuation": metrics(continuation_correct),
        "reversal": metrics(reversal_correct),
        "verdict": "signal_detected"
        if any(metrics(w)["signal"] for w in (continuation_correct, reversal_correct))
        else "no_statistically_clear_directional_signal",
        "limitations": [
            "Coinbase close direction is a proxy; Kalshi settles on CF Benchmarks RTI averages.",
            "No Kalshi quote, fill, fee, adverse-selection, or BRTI data is included.",
            "A positive result is not promotion evidence and must clear the causal promotion "
            "gate separately.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTC-USD")
    parser.add_argument("--days", type=int, default=30, choices=range(1, 91))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {"source": "Coinbase Exchange", "symbol": args.symbol, "days_requested": args.days}
    report.update(study(fetch_coinbase_15m(args.symbol, args.days)))
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
