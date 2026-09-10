"""Deliberate foreground capture/import for KXBTC15M validation data.

This command never schedules itself and never runs unattended.

- ``--import-jsonl`` ingests operator-exported observations with the schema of
  the corresponding storage table.
- ``--capture`` pulls KXBTC15M market + contract-candle history from the
  unauthenticated Kalshi public client.
- ``--poll-brti`` runs a FOREGROUND BRTI polling loop (Ctrl+C or ``--duration``
  stops it) that records `observed_at` / `available_at` honestly and logs —
  never fills — gaps. Choose the data source with ``--brti-source``:
    * ``kalshi`` — the real index, via Kalshi's authenticated CF Benchmarks
      REST passthrough (read-only market data; needs ``KALSHI_KEY_ID`` and
      ``secrets/kalshi_private_key.pem``). This is what a validation capture
      uses.
    * ``fake`` — a synthetic random walk, for wiring and tests only. Prints a
      loud warning and MUST NOT feed a validation run.
- ``--backfill-funding`` does a one-shot idempotent pull of Kalshi crypto-perp
  funding history (``/margin/funding_rates/historical`` — read-only,
  authenticated). Funding IS backfillable, so this is not a poll.
- ``--poll-perp-marks`` runs a FOREGROUND loop over ``/margin/markets``
  (read-only, authenticated) recording each crypto perp's settlement mark with
  honest ``observed_at`` / ``available_at`` and logged — never filled — gaps.
  Kalshi publishes no historical mark series, so a live poll is the only way.
- ``--capture-funding-estimates`` takes one authenticated, read-only snapshot
  of each selected perp's current funding estimate. Estimates are not
  backfillable, so this records only what is observable at capture time.
- ``--report`` prints gap analysis for every observation kind.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import sys
import time
import uuid
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from kalshi_bot.config.settings import get_settings  # noqa: E402
from kalshi_bot.data.brti import (  # noqa: E402
    BRTIReadingRaw,
    BRTISource,
    CallableBRTISource,
    KalshiBRTISource,
    poll_brti,
)
from kalshi_bot.data.kalshi.client import KalshiPublicClient  # noqa: E402
from kalshi_bot.data.kalshi.parse import parse_candle, parse_market  # noqa: E402
from kalshi_bot.data.perps import (  # noqa: E402
    KalshiPerpMarkSource,
    backfill_funding,
    capture_funding_estimates,
    poll_perp_marks,
    resolve_crypto_perp_tickers,
)
from kalshi_bot.storage import (  # noqa: E402
    BRTIObservation,
    Candle,
    KalshiMarket,
    OrderBookSnapshot,
    PerpFundingEstimateObservation,
    PerpFundingObservation,
    PerpMarkObservation,
    PublicTrade,
    create_all_tables,
    get_engine,
    get_session_factory,
)

KINDS = {
    "brti": BRTIObservation,
    "l2": OrderBookSnapshot,
    "trade": PublicTrade,
    "perp_mark": PerpMarkObservation,
    "perp_funding": PerpFundingObservation,
    "perp_funding_estimate": PerpFundingEstimateObservation,
}
BRTI_SOURCES = ("kalshi", "fake")

# Asset symbols whose Kalshi crypto perps we capture by default — the nine
# registry crypto assets. `resolve_crypto_perp_tickers` maps these to live
# KX<ASSET>PERP tickers (and silently drops any the exchange isn't listing).
DEFAULT_PERP_ASSETS = ("BTC", "ETH", "SOL", "XRP")


def import_jsonl(session, path: Path, kind: str, session_id: str) -> int:
    model = KINDS[kind]
    count = 0
    now = int(time.time())
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            row.setdefault("capture_session_id", session_id)
            row.setdefault("fetched_at", now)
            row.setdefault("provenance", {"operator_run": True, "import_file": str(path)})
            session.add(model(**row))
            count += 1
    session.commit()
    return count


def gap_report(session, kind: str, *, period_seconds: int | None = None) -> dict[str, object]:
    """Summarize first/last timestamps, gaps, and capture sessions.

    For the per-market perp kinds (``perp_mark``, ``perp_funding``) each
    market's series is reported separately so one perp's stall isn't read as
    a gap in another's.
    """
    model = KINDS[kind]
    rows = session.execute(select(model).order_by(model.observed_at)).scalars().all()
    if kind in ("perp_mark", "perp_funding", "perp_funding_estimate"):
        by_ticker: dict[str, list[int]] = {}
        for r in rows:
            by_ticker.setdefault(r.market_ticker, []).append(r.observed_at)
        return {
            "kind": kind,
            "rows": len(rows),
            "markets": {
                ticker: {
                    "first_ts": min(ts),
                    "last_ts": max(ts),
                    "rows": len(ts),
                    "gap_count": (
                        sum(1 for a, b in itertools.pairwise(sorted(ts)) if b - a > period_seconds)
                        if period_seconds
                        else 0
                    ),
                }
                for ticker, ts in sorted(by_ticker.items())
            },
            "capture_sessions": sorted(
                {r.capture_session_id for r in rows if r.capture_session_id}
            ),
        }
    timestamps = [r.observed_at for r in rows]
    gaps = []
    if period_seconds:
        gaps = [(a, b, b - a) for a, b in itertools.pairwise(timestamps) if b - a > period_seconds]
    return {
        "kind": kind,
        "first_ts": min(timestamps) if timestamps else None,
        "last_ts": max(timestamps) if timestamps else None,
        "rows": len(rows),
        "gap_count": len(gaps),
        "gaps": gaps,
        "capture_sessions": sorted({r.capture_session_id for r in rows if r.capture_session_id}),
    }


def capture_kxbtc15m(session, *, start_ts: int, end_ts: int, period_minutes: int,
                     max_markets: int, session_id: str) -> tuple[int, int]:
    markets = candles = 0
    now = int(time.time())
    with KalshiPublicClient(max_reads_per_second=8) as client:
        for raw in client.iter_markets(series_ticker="KXBTC15M", status="settled",
                                       min_close_ts=start_ts, max_close_ts=end_ts):
            if max_markets and markets >= max_markets:
                break
            endpoint = "/markets?series_ticker=KXBTC15M&status=settled"
            parsed = parse_market(raw, series_ticker="KXBTC15M", capture_session_id=session_id,
                                  source_endpoint=endpoint, fetched_at=now)
            session.merge(KalshiMarket(**parsed))
            raw_candles = client.get_candlesticks(
                "KXBTC15M", raw["ticker"], start_ts=parsed["open_ts"],
                end_ts=parsed["close_ts"], period_minutes=period_minutes
            )
            for item in raw_candles:
                session.add(Candle(**parse_candle(
                    item, market_ticker=raw["ticker"], series_ticker="KXBTC15M",
                    period_minutes=period_minutes, capture_session_id=session_id,
                    source_endpoint=f"/series/KXBTC15M/markets/{raw['ticker']}/candlesticks",
                    fetched_at=now)))
            markets += 1
            candles += len(raw_candles)
    session.commit()
    return markets, candles


def _make_fake_brti_source() -> BRTISource:
    """A synthetic BRTI random walk around $100k. For wiring and tests ONLY —
    it is not real index data and must never feed a validation run. The real
    source (CF Benchmarks real-time API, a licensed historical export, or a
    Kalshi index endpoint) is an unmade operator decision."""
    state = {"value": 100_000.0}

    def _fetch() -> BRTIReadingRaw:
        state["value"] *= math.exp(random.gauss(0.0, 0.0002))
        return BRTIReadingRaw(
            observed_at=int(time.time()),
            value=state["value"],
            source="fake:random-walk",
            extra={"synthetic": True},
        )

    return CallableBRTISource(_fetch, name="fake:random-walk")


# CF Benchmarks Real-Time Index ids for the Kalshi crypto event series
# (verified live through the passthrough 2026-09-07). BRTI is Bitcoin's; the
# rest follow the <ASSET>USD_RTI convention.
CRYPTO_RTI_INDICES = {
    "BTC": "BRTI",
    "ETH": "ETHUSD_RTI",
    "SOL": "SOLUSD_RTI",
    "XRP": "XRPUSD_RTI",
    "DOGE": "DOGEUSD_RTI",
    "BNB": "BNBUSD_RTI",
    "HYPE": "HYPEUSD_RTI",
    "NEAR": "NEARUSD_RTI",
    "ZEC": "ZECUSD_RTI",
}


def _resolve_brti_sources(name: str, index_ids: list[str]) -> list[BRTISource]:
    if name == "fake":
        return [_make_fake_brti_source()]
    if name == "kalshi":
        settings = get_settings()
        key_id = settings.kalshi_key_id
        if key_id is None:
            raise SystemExit(
                "--brti-source kalshi needs KALSHI_KEY_ID set (in .env or the "
                "environment). The BRTI passthrough is an authenticated Kalshi "
                "endpoint."
            )
        key_path = settings.kalshi_private_key_path
        if not key_path.exists():
            raise SystemExit(
                f"--brti-source kalshi needs the RSA key at {key_path} "
                "(kalshi_private_key_path). It is gitignored; restore it first."
            )
        return [
            KalshiBRTISource(
                key_id=key_id.get_secret_value(),
                private_key_path=key_path,
                index_id=idx,
            )
            for idx in index_ids
        ]
    raise SystemExit(f"--brti-source {name!r} is not a known source ({BRTI_SOURCES}).")


def _parse_index_ids(raw: list[str] | None) -> list[str]:
    """`--brti-index` accepts asset symbols (BTC, ETH), raw CF Benchmarks ids
    (BRTI, SOLUSD_RTI), 'all', or a comma-list of those; repeatable."""
    tokens: list[str] = []
    for chunk in raw or ["BTC"]:
        tokens.extend(t.strip() for t in chunk.split(",") if t.strip())
    resolved: list[str] = []
    for tok in tokens:
        up = tok.upper()
        if up == "ALL":
            resolved.extend(CRYPTO_RTI_INDICES.values())
        elif up in CRYPTO_RTI_INDICES:
            resolved.append(CRYPTO_RTI_INDICES[up])
        else:
            resolved.append(tok)  # assume a raw CF Benchmarks id
    # de-dupe, preserve order
    seen: set[str] = set()
    return [i for i in resolved if not (i in seen or seen.add(i))]


def _kalshi_margin_client():
    """A read-only KalshiMarginClient built from settings. Both perp captures
    make only authenticated `/margin/*` GET calls; `paper_trading=True` keeps
    the order-placement guard armed regardless."""
    from kalshi_bot.execution.kalshi_margin_client import KalshiMarginClient

    settings = get_settings()
    key_id = settings.kalshi_key_id
    if key_id is None:
        raise SystemExit(
            "perp capture needs KALSHI_KEY_ID set (in .env or the environment); "
            "the /margin endpoints are authenticated."
        )
    key_path = settings.kalshi_private_key_path
    if not key_path.exists():
        raise SystemExit(
            f"perp capture needs the RSA key at {key_path} (kalshi_private_key_path). "
            "It is gitignored; restore it first."
        )
    return KalshiMarginClient(
        key_id=key_id.get_secret_value(),
        private_key_path=key_path,
        use_demo_env=settings.kalshi_use_demo_env,
        paper_trading=True,
    )


def _parse_perp_assets(raw: list[str] | None) -> list[str]:
    """`--perp-asset` accepts asset symbols (BTC, ETH), full perp tickers
    (KXBTCPERP), 'all', or a comma-list; repeatable. 'all' / default -> the
    nine registry crypto assets."""
    if not raw:
        return list(DEFAULT_PERP_ASSETS)
    tokens: list[str] = []
    for chunk in raw:
        tokens.extend(t.strip() for t in chunk.split(",") if t.strip())
    resolved: list[str] = []
    for tok in tokens:
        up = tok.upper()
        if up == "ALL":
            resolved.extend(DEFAULT_PERP_ASSETS)
        elif up.startswith("KX") and up.endswith("PERP"):
            resolved.append(up.removeprefix("KX").removesuffix("PERP"))
        else:
            resolved.append(up)
    seen: set[str] = set()
    return [a for a in resolved if not (a in seen or seen.add(a))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-jsonl", type=Path)
    parser.add_argument("--kind", choices=sorted(KINDS))
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--start-ts", type=int)
    parser.add_argument("--end-ts", type=int)
    parser.add_argument("--period", type=int, default=1)
    parser.add_argument("--max-markets", type=int, default=0)
    parser.add_argument("--report", action="store_true")
    parser.add_argument(
        "--poll-brti", action="store_true",
        help="run a foreground BRTI polling loop (Ctrl+C or --duration stops it)",
    )
    parser.add_argument(
        "--brti-source", choices=BRTI_SOURCES, default="kalshi",
        help="BRTI data source: 'kalshi' (real, authenticated CF Benchmarks passthrough) "
        "or 'fake' (synthetic, tests only)",
    )
    parser.add_argument(
        "--brti-index", action="append", default=None,
        help="index(es) to poll: asset symbol (BTC, ETH, SOL...), raw CF Benchmarks id "
        "(BRTI, SOLUSD_RTI), 'all', or a comma-list. Repeatable. Default: BTC.",
    )
    parser.add_argument(
        "--interval", type=float, default=60.0,
        help="poll interval in seconds (shared by --poll-brti and --poll-perp-marks)",
    )
    parser.add_argument(
        "--duration", type=float, default=3600.0,
        help="how long a poll loop runs, seconds (it does not restart itself)",
    )
    parser.add_argument(
        "--backfill-funding", action="store_true",
        help="one-shot idempotent pull of Kalshi crypto-perp funding history "
        "(read-only, authenticated). Uses --start-ts/--end-ts, defaulting to the "
        "last 90 days.",
    )
    parser.add_argument(
        "--poll-perp-marks", action="store_true",
        help="run a foreground loop over /margin/markets recording crypto perp "
        "settlement marks (Ctrl+C or --duration stops it)",
    )
    parser.add_argument(
        "--capture-funding-estimates", action="store_true",
        help="take one read-only snapshot of the current funding estimate for each selected "
        "crypto perp (not backfillable)",
    )
    parser.add_argument(
        "--perp-asset", action="append", default=None,
        help="perp(s) for --backfill-funding / --poll-perp-marks / "
        "--capture-funding-estimates: asset symbol "
        "(BTC, ETH...), full ticker (KXBTCPERP), 'all', or a comma-list. "
        "Repeatable. Default: the nine registry crypto assets.",
    )
    args = parser.parse_args()
    if args.import_jsonl and not args.kind:
        parser.error("--kind is required with --import-jsonl")
    if args.capture and (args.start_ts is None or args.end_ts is None):
        parser.error("--capture requires --start-ts and --end-ts")
    engine = get_engine()
    create_all_tables(engine)
    session_id = f"manual-{uuid.uuid4().hex}"
    with get_session_factory(engine)() as session:
        if args.import_jsonl:
            print(f"imported={import_jsonl(session, args.import_jsonl, args.kind, session_id)}")
        if args.capture:
            print("capture=", capture_kxbtc15m(
                session, start_ts=args.start_ts, end_ts=args.end_ts,
                period_minutes=args.period, max_markets=args.max_markets, session_id=session_id
            ))
        if args.poll_brti:
            index_ids = _parse_index_ids(args.brti_index)
            sources = _resolve_brti_sources(args.brti_source, index_ids)
            if args.brti_source == "fake":
                print(
                    "WARNING: --brti-source fake is synthetic data. It is safe to "
                    "exercise the loop but MUST NOT be used for a validation run."
                )
            else:
                print(f"polling {len(sources)} index feed(s): {', '.join(index_ids)}")
            result = poll_brti(
                session, sources,
                interval_s=args.interval, duration_s=args.duration, session_id=session_id,
            )
            print("poll_brti=", json.dumps(result.as_dict(), sort_keys=True))
        if args.backfill_funding:
            now = int(time.time())
            start_ts = args.start_ts if args.start_ts is not None else now - 90 * 86_400
            end_ts = args.end_ts if args.end_ts is not None else now
            assets = _parse_perp_assets(args.perp_asset)
            with _kalshi_margin_client() as client:
                tickers = resolve_crypto_perp_tickers(client, wanted=assets)
                if not tickers:
                    print(f"no active crypto perps match {assets}")
                else:
                    print(f"backfilling funding for {len(tickers)} perp(s): {', '.join(tickers)}")
                    fres = backfill_funding(
                        session, client, tickers=tickers,
                        start_ts=start_ts, end_ts=end_ts, session_id=session_id,
                    )
                    print("backfill_funding=", json.dumps(fres.as_dict(), sort_keys=True))
        if args.poll_perp_marks:
            assets = _parse_perp_assets(args.perp_asset)
            with _kalshi_margin_client() as client:
                tickers = resolve_crypto_perp_tickers(client, wanted=assets)
                if not tickers:
                    print(f"no active crypto perps match {assets}")
                else:
                    print(f"polling {len(tickers)} perp mark feed(s): {', '.join(tickers)}")
                    source = KalshiPerpMarkSource(client, tickers=tickers)
                    mres = poll_perp_marks(
                        session, source,
                        interval_s=args.interval, duration_s=args.duration,
                        session_id=session_id,
                    )
                    print("poll_perp_marks=", json.dumps(mres.as_dict(), sort_keys=True))
        if args.capture_funding_estimates:
            assets = _parse_perp_assets(args.perp_asset)
            with _kalshi_margin_client() as client:
                tickers = resolve_crypto_perp_tickers(client, wanted=assets)
                if not tickers:
                    print(f"no active crypto perps match {assets}")
                else:
                    print(
                        f"capturing funding estimates for {len(tickers)} perp(s): "
                        f"{', '.join(tickers)}"
                    )
                    eres = capture_funding_estimates(
                        session, client, tickers=tickers, session_id=session_id
                    )
                    print("capture_funding_estimates=", json.dumps(eres.as_dict(), sort_keys=True))
        if args.report:
            for kind in KINDS:
                print(json.dumps(gap_report(session, kind), sort_keys=True))


if __name__ == "__main__":
    main()
