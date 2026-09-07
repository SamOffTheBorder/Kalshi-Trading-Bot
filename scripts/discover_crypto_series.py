"""Run an explicit, foreground discovery pass for configured crypto series.

This validates the registry against Kalshi's public API and persists the raw
series/market metadata. It is evidence only: an eligible discovery result does
not promote an asset or authorize an order.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from kalshi_bot.config.crypto_registry import DEFAULT_CRYPTO_REGISTRY, get_asset  # noqa: E402
from kalshi_bot.data.kalshi.client import KalshiPublicClient  # noqa: E402
from kalshi_bot.discovery import EventSeriesDiscovery  # noqa: E402
from kalshi_bot.storage import create_all_tables, get_engine, get_session_factory  # noqa: E402


def _quote_summary(snapshot_metadata: dict) -> dict:
    """Return only current, non-sensitive quote/liveness fields for the report."""
    series = snapshot_metadata.get("series", {})
    return {
        "frequency": series.get("frequency") or series.get("cadence"),
        "contract_terms_url": series.get("contract_terms_url"),
        "settlement_sources": series.get("settlement_sources", []),
        "active_market_count": snapshot_metadata.get("active_market_count", 0),
        "expected_shape": snapshot_metadata.get("market_shape"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", action="append", help="asset ID to inspect; repeatable")
    parser.add_argument("--output", type=Path, help="write JSON report to this path")
    args = parser.parse_args()

    selected = (
        tuple(get_asset(asset) for asset in args.asset) if args.asset else DEFAULT_CRYPTO_REGISTRY
    )
    engine = get_engine()
    create_all_tables(engine)
    session_factory = get_session_factory(engine)
    reports: list[dict] = []

    with KalshiPublicClient(max_reads_per_second=8) as client, session_factory() as session:
        discovery = EventSeriesDiscovery(client)
        for asset in selected:
            if not asset.event_instruments:
                reports.append(
                    {
                        "asset_id": asset.asset_id,
                        "event_series": [],
                        "reason": "no_event_series_configured",
                    }
                )
                continue
            snapshots = discovery.refresh(asset, session)
            reports.append(
                {
                    "asset_id": asset.asset_id,
                    "event_series": [
                        {
                            "cadence": snapshot.cadence,
                            "series_ticker": snapshot.identifier,
                            "eligible": snapshot.eligible,
                            "failure_reason": snapshot.failure_reason,
                            "checked_at": snapshot.checked_at,
                            "metadata": _quote_summary(snapshot.metadata),
                        }
                        for snapshot in snapshots
                    ],
                }
            )

    report = {"registry_assets": len(selected), "assets": reports}
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return (
        0
        if all(
            item.get("reason") == "no_event_series_configured"
            or all(row["eligible"] for row in item["event_series"])
            for item in reports
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
