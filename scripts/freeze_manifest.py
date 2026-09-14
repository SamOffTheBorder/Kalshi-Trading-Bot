"""Freeze a provenance-aware manifest from captured crypto observations.

This command is deliberately a read path over the capture tables.  It does
not manufacture observations or relabel reconstructed data as native.  The
result is an immutable ``DatasetManifest`` written through
``persist_manifest``; repeating the command with unchanged inputs is
idempotent.

Examples::

    python scripts/freeze_manifest.py --asset BTC --source spot --source brti
    python scripts/freeze_manifest.py --asset BTC --source brti --output report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from kalshi_bot.config.crypto_registry import DEFAULT_CRYPTO_REGISTRY, get_asset  # noqa: E402
from kalshi_bot.config.settings import Settings  # noqa: E402
from kalshi_bot.data.manifests import (  # noqa: E402
    classify_provenance,
    manifest_hash,
    persist_manifest,
)
from kalshi_bot.storage.db import create_all_tables, get_engine, get_session_factory  # noqa: E402
from kalshi_bot.storage.models import BRTIObservation, DatasetManifest, SpotCandle  # noqa: E402

PARSER_VERSION = "captured-observations-v1"
FEATURE_VERSION = "manifest-coverage-v1"


@dataclass(frozen=True)
class _Partition:
    key: str
    source_id: str
    start_ts: int
    end_ts: int
    rows: int
    provenance: str
    detail: dict[str, Any]


def _parse_ts(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())


def _git_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _config_hash() -> str:
    payload = [asset.model_dump(mode="json") for asset in DEFAULT_CRYPTO_REGISTRY]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _contains_reconstructed(value: object) -> bool:
    if isinstance(value, dict):
        if value.get("synthetic") is True:
            return True
        return any(_contains_reconstructed(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_reconstructed(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return "reconstruct" in lowered or "synthetic" in lowered or lowered.startswith("fake:")
    return False


def _provenance(rows: list[object], *, source: str) -> str:
    """Classify the queried rows without assuming a safe label.

    ``SpotCandle`` predates the explicit provenance JSON field and is itself
    the direct captured-spot table, so a missing value there is source-native.
    Any explicit reconstructed/synthetic marker, including a fake BRTI
    source, wins and makes the partition reconstructed.
    """
    if source == "brti" and any(
        str(getattr(row, "source", "")).lower().startswith("fake:") for row in rows
    ):
        return "reconstructed"
    if any(_contains_reconstructed(getattr(row, "provenance", None)) for row in rows):
        return "reconstructed"
    return "source_native"


def _bounds(rows: list[object], *, start_attr: str, end_attr: str) -> tuple[int, int]:
    starts = [int(getattr(row, start_attr)) for row in rows]
    ends = [int(getattr(row, end_attr)) for row in rows]
    return min(starts), max(ends) + 1


def _source_name(source: str, asset_id: str) -> str:
    normalized = source.strip().lower()
    if normalized in {"brti", "brtiobservation", "brti_observation"}:
        return "brti"
    if normalized in {"spot", "spotcandle", "spot_candle"}:
        return "spot"
    raise ValueError(f"unsupported capture source {source!r}; use spot or brti")


def _load_partitions(
    session,
    *,
    asset_id: str,
    sources: tuple[str, ...],
    start_ts: int | None,
    end_ts: int | None,
) -> list[_Partition]:
    asset = get_asset(asset_id)
    partitions: list[_Partition] = []
    for requested in sources:
        source = _source_name(requested, asset_id)
        if source == "spot":
            symbols = asset.spot_symbols
            rows = list(
                session.query(SpotCandle)
                .filter(SpotCandle.symbol.in_(symbols))
                .order_by(SpotCandle.open_ts)
                .all()
            )
            if start_ts is not None:
                rows = [row for row in rows if row.open_ts >= start_ts]
            if end_ts is not None:
                rows = [row for row in rows if row.open_ts <= end_ts]
            if not rows:
                raise ValueError(f"no captured spot rows for {asset_id}")
            first, last = _bounds(rows, start_attr="open_ts", end_attr="open_ts")
            periods = sorted({int(row.period_minutes) for row in rows})
            partition_key = f"{asset_id}:spot:{','.join(map(str, periods))}m"
            partitions.append(
                _Partition(
                    partition_key,
                    f"capture:spot:{asset_id}",
                    first,
                    last,
                    len(rows),
                    _provenance(rows, source=source),
                    {"symbols": sorted(symbols), "period_minutes": periods},
                )
            )
        else:
            index_source = "kalshi:cfbenchmarks/BRTI" if asset_id == "BTC" else (
                f"kalshi:cfbenchmarks/{asset_id}USD_RTI"
            )
            rows = list(
                session.query(BRTIObservation)
                .filter(BRTIObservation.source == index_source)
                .order_by(BRTIObservation.observed_at)
                .all()
            )
            if start_ts is not None:
                rows = [row for row in rows if row.observed_at >= start_ts]
            if end_ts is not None:
                rows = [row for row in rows if row.observed_at <= end_ts]
            if not rows:
                raise ValueError(f"no captured {index_source} rows for {asset_id}")
            first, last = _bounds(rows, start_attr="observed_at", end_attr="observed_at")
            partitions.append(
                _Partition(
                    f"{asset_id}:brti:{index_source}",
                    f"capture:brti:{asset_id}",
                    first,
                    last,
                    len(rows),
                    _provenance(rows, source=source),
                    {"index_source": index_source},
                )
            )
    return partitions


def build_manifest_spec(
    session,
    *,
    asset_id: str,
    sources: tuple[str, ...],
    start_ts: int | None = None,
    end_ts: int | None = None,
):
    """Build a manifest from actual captured rows; exposed for unit tests."""
    asset_id = asset_id.upper()
    if not sources:
        raise ValueError("at least one source is required")
    if start_ts is not None and end_ts is not None and start_ts >= end_ts:
        raise ValueError("start_ts must precede end_ts")
    partitions = _load_partitions(
        session,
        asset_id=asset_id,
        sources=tuple(sources),
        start_ts=start_ts,
        end_ts=end_ts,
    )
    actual_start = max(start_ts if start_ts is not None else min(p.start_ts for p in partitions),
                       min(p.start_ts for p in partitions))
    actual_end = min(end_ts if end_ts is not None else max(p.end_ts for p in partitions),
                     max(p.end_ts for p in partitions))
    if actual_start >= actual_end:
        raise ValueError("captured source range is empty")
    coverage = {
        "asset_id": asset_id,
        "partitions": {
            p.key: {
                "source_id": p.source_id,
                "rows": p.rows,
                "start_ts": p.start_ts,
                "end_ts": p.end_ts,
                "provenance": p.provenance,
                **p.detail,
            }
            for p in partitions
        },
    }
    partition_provenance = {p.key: p.provenance for p in partitions}
    from kalshi_bot.data.manifests import ManifestSpec

    return ManifestSpec(
        asset_ids=(asset_id,),
        source_ids=tuple(p.source_id for p in partitions),
        start_ts=actual_start,
        end_ts=actual_end,
        parser_version=PARSER_VERSION,
        feature_version=FEATURE_VERSION,
        code_revision=_git_revision(),
        config_sha256=_config_hash(),
        filter_rules={"asset": asset_id, "sources": list(sources), "captured_rows_only": True},
        coverage_summary=coverage,
        normalized_partitions=tuple(p.key for p in partitions),
        source_mappings={"spot_symbols": list(get_asset(asset_id).spot_symbols)},
        partition_provenance=partition_provenance,
    )


def freeze_manifest(session, spec, *, created_at: int | None = None) -> dict[str, object]:
    digest = manifest_hash(spec)
    existing = session.query(DatasetManifest).filter_by(manifest_sha256=digest).one_or_none()
    row = persist_manifest(
        session,
        spec,
        created_at=int(time.time()) if created_at is None else created_at,
    )
    session.commit()
    provenance = row.provenance_class or classify_provenance(spec.partition_provenance)
    return {
        "manifest_id": row.id,
        "manifest_sha256": row.manifest_sha256,
        "asset_ids": row.asset_ids,
        "source_ids": row.source_ids,
        "start_ts": row.start_ts,
        "end_ts": row.end_ts,
        "provenance_class": provenance,
        "source_native": provenance == "source_native",
        "reused": existing is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", required=True, help="registry asset, e.g. BTC")
    parser.add_argument("--source", action="append", required=True, help="spot or brti; repeatable")
    parser.add_argument("--start", "--start-ts", dest="start_ts", type=_parse_ts)
    parser.add_argument("--end", "--end-ts", dest="end_ts", type=_parse_ts)
    parser.add_argument("--db", type=Path, default=Path("data/kalshi_bot.db"))
    parser.add_argument("--output", type=Path, help="write the JSON report to this path")
    args = parser.parse_args()
    if (args.start_ts is None) != (args.end_ts is None):
        parser.error("--start and --end must be supplied together")
    try:
        get_asset(args.asset)
        engine = get_engine(Settings(db_path=args.db))
        create_all_tables(engine)
        with get_session_factory(engine)() as session:
            spec = build_manifest_spec(
                session,
                asset_id=args.asset,
                sources=tuple(args.source),
                start_ts=args.start_ts,
                end_ts=args.end_ts,
            )
            report = freeze_manifest(session, spec)
    except (KeyError, ValueError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
