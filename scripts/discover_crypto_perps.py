"""Run an explicit, foreground discovery pass for configured crypto perps.

Perp metadata lives under Kalshi's authenticated ``/margin`` read API, so
this command needs the configured key but never calls an order endpoint.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from kalshi_bot.config.crypto_registry import DEFAULT_CRYPTO_REGISTRY, get_asset  # noqa: E402
from kalshi_bot.config.settings import get_settings  # noqa: E402
from kalshi_bot.discovery import PerpDiscovery  # noqa: E402
from kalshi_bot.execution.kalshi_margin_client import KalshiMarginClient  # noqa: E402
from kalshi_bot.storage import create_all_tables, get_engine, get_session_factory  # noqa: E402


def run_discovery(
    client, session, assets=DEFAULT_CRYPTO_REGISTRY, *, clock=time.time
) -> list[dict[str, object]]:
    """Persist one perp snapshot per configured asset and return report rows."""
    discovery = PerpDiscovery(client, clock=clock)
    reports: list[dict[str, object]] = []
    for asset in assets:
        snapshot = discovery.refresh(asset, session) if asset.perp is not None else None
        if snapshot is None:
            reports.append({"asset_id": asset.asset_id, "configured": False})
            continue
        reports.append(
            {
                "asset_id": asset.asset_id,
                "configured": True,
                "market_ticker": snapshot.identifier,
                "eligible": snapshot.eligible,
                "failure_reason": snapshot.failure_reason,
                "checked_at": snapshot.checked_at,
                "metadata": snapshot.metadata,
            }
        )
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", action="append", help="asset ID to inspect; repeatable")
    parser.add_argument("--db", type=Path, default=Path("data/kalshi_bot.db"))
    parser.add_argument("--output", type=Path, help="write JSON report to this path")
    args = parser.parse_args()
    selected = (
        tuple(get_asset(asset) for asset in args.asset)
        if args.asset
        else DEFAULT_CRYPTO_REGISTRY
    )
    settings = get_settings()
    if settings.kalshi_key_id is None:
        parser.error("KALSHI_KEY_ID is required for the authenticated margin read endpoint")
    engine = get_engine(settings.model_copy(update={"db_path": args.db}))
    create_all_tables(engine)
    with KalshiMarginClient(
        key_id=settings.kalshi_key_id.get_secret_value(),
        private_key_path=settings.kalshi_private_key_path,
        use_demo_env=settings.kalshi_use_demo_env,
        paper_trading=settings.paper_trading,
        live_trading_confirmation_phrase=(
            settings.live_trading_confirmation_phrase.get_secret_value()
            if settings.live_trading_confirmation_phrase
            else None
        ),
        max_reads_per_second=8,
    ) as client, get_session_factory(engine)() as session:
        assets = run_discovery(client, session, selected)
    report = {"registry_assets": len(selected), "assets": assets}
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if all(not item.get("configured") or item.get("eligible") for item in assets) else 1


if __name__ == "__main__":
    raise SystemExit(main())
