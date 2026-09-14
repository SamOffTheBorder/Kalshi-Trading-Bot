"""One-shot, idempotent backfill of Kalshi crypto-perp funding history.

Unlike the BRTI index and the perp mark price, Kalshi *does* serve realized
funding history: ``GET /trade-api/v2/margin/funding_rates/historical`` returns
the 8-hourly settlements (04:00 / 12:00 / 20:00 UTC) for a perp market, newest
first, as ``{"funding_rate": <float>, "funding_time": <ISO>, "mark_price":
"<per-contract $>", "market_ticker": "<KX...PERP>"}``.

So this is a plain backfill, not a foreground poll: call it once (or again
later to extend the window) and it writes any settlement it does not already
have. ``funding_rate`` is legitimately ``0`` in many intervals — that is a
real observation, persisted as ``0.0``, not a gap.

``observed_at`` is the settlement instant. ``available_at`` is set equal to it:
a realized funding rate is known exactly at settlement and the backfill will
not invent an earlier availability it cannot defend (the same discipline the
BRTI capture applies to ``observed_at`` vs ``available_at``).

This module makes authenticated **read-only** ``/margin/*`` GET calls. It
places nothing and touches no ``/orders`` path.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.storage.models import PerpFundingEstimateObservation, PerpFundingObservation


class _FundingClient(Protocol):
    """The two read-only methods the funding backfill needs from a margin
    client. `KalshiMarginClient` satisfies this structurally."""

    def get_historical_funding_rates(
        self,
        *,
        ticker: str | None = ...,
        start_ts: int | None = ...,
        end_ts: int | None = ...,
    ) -> dict[str, Any]: ...

    def get_markets(self, *, status: str | None = ...) -> dict[str, Any]: ...

    def get_funding_rate_estimate(self, ticker: str) -> dict[str, Any]: ...


SOURCE_LABEL = "kalshi:margin/funding_rates/historical"
ENDPOINT = "/margin/funding_rates/historical"
ESTIMATE_SOURCE_LABEL = "kalshi:margin/funding_rates/estimate"
ESTIMATE_ENDPOINT = "/margin/funding_rates/estimate"


@dataclass
class FundingBackfillResult:
    tickers: tuple[str, ...] = ()
    rows_seen: int = 0
    persisted: int = 0
    duplicates_skipped: int = 0
    malformed_skipped: int = 0
    errors: int = 0
    first_observed_at: int | None = None
    last_observed_at: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "tickers": list(self.tickers),
            "rows_seen": self.rows_seen,
            "persisted": self.persisted,
            "duplicates_skipped": self.duplicates_skipped,
            "malformed_skipped": self.malformed_skipped,
            "errors": self.errors,
            "first_observed_at": self.first_observed_at,
            "last_observed_at": self.last_observed_at,
        }


@dataclass
class FundingEstimateCaptureResult:
    """Outcome of one operator-invoked current-funding-estimate snapshot."""

    tickers: tuple[str, ...] = ()
    rows_seen: int = 0
    persisted: int = 0
    duplicates_skipped: int = 0
    malformed_skipped: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "tickers": list(self.tickers),
            "rows_seen": self.rows_seen,
            "persisted": self.persisted,
            "duplicates_skipped": self.duplicates_skipped,
            "malformed_skipped": self.malformed_skipped,
            "errors": self.errors,
        }


def _parse_funding_time(raw: object) -> int | None:
    """`funding_time` is ISO-8601 UTC (e.g. "2026-09-07T04:00:00Z"). Accept an
    epoch int/float too, in case the shape ever changes."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        val = int(raw)
        # A plausibly-ms timestamp -> seconds.
        return val // 1000 if val > 10_000_000_000 else val
    if isinstance(raw, str):
        text = raw.strip().replace("Z", "+00:00")
        try:
            return int(datetime.fromisoformat(text).timestamp())
        except ValueError:
            return None
    return None


def _existing_observed_at(session: Session, ticker: str) -> set[int]:
    rows = session.execute(
        select(PerpFundingObservation.observed_at).where(
            PerpFundingObservation.market_ticker == ticker
        )
    ).scalars()
    return set(rows)


def _existing_estimate_observed_at(session: Session, ticker: str) -> set[int]:
    rows = session.execute(
        select(PerpFundingEstimateObservation.observed_at).where(
            PerpFundingEstimateObservation.market_ticker == ticker
        )
    ).scalars()
    return set(rows)


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def capture_funding_estimates(
    session: Session,
    client: _FundingClient,
    *,
    tickers: Sequence[str],
    session_id: str,
    now_fn: Callable[[], float] = time.time,
) -> FundingEstimateCaptureResult:
    """Persist one current funding-estimate snapshot per requested ticker.

    Estimates have no historical endpoint, so this deliberately records only
    the value readable now. A malformed response or one ticker's read failure
    is isolated; other tickers are still captured. Repeating a request with
    the same exchange ``computed_time`` is idempotent.
    """
    result = FundingEstimateCaptureResult(tickers=tuple(tickers))
    for ticker in tickers:
        fetched_at = int(now_fn())
        try:
            body = client.get_funding_rate_estimate(ticker)
        except Exception as exc:  # one ticker down must not stop the others
            result.errors += 1
            logger.warning("funding estimate: {} request failed: {}", ticker, exc)
            continue

        result.rows_seen += 1
        if not isinstance(body, dict):
            result.malformed_skipped += 1
            continue
        rate = _finite_float(body.get("funding_rate"))
        observed_at = _parse_funding_time(body.get("computed_time"))
        returned_ticker = body.get("market_ticker")
        if rate is None or observed_at is None or returned_ticker != ticker:
            result.malformed_skipped += 1
            logger.warning("funding estimate: {} returned an unusable response", ticker)
            continue

        already = _existing_estimate_observed_at(session, ticker)
        if observed_at in already:
            result.duplicates_skipped += 1
            continue
        session.add(
            PerpFundingEstimateObservation(
                market_ticker=ticker,
                observed_at=observed_at,
                available_at=max(fetched_at, observed_at),
                funding_rate=rate,
                mark_price_dollars=(
                    str(body["mark_price"]) if body.get("mark_price") is not None else None
                ),
                next_funding_time=(
                    str(body["next_funding_time"])
                    if body.get("next_funding_time") is not None
                    else None
                ),
                source=ESTIMATE_SOURCE_LABEL,
                capture_session_id=session_id,
                source_endpoint=ESTIMATE_ENDPOINT,
                fetched_at=fetched_at,
                provenance={"operator_run": True},
            )
        )
        result.persisted += 1
    session.commit()
    logger.info("funding estimate capture finished: {}", result.as_dict())
    return result


def backfill_funding(
    session: Session,
    client: _FundingClient,
    *,
    tickers: Sequence[str],
    start_ts: int,
    end_ts: int,
    session_id: str,
) -> FundingBackfillResult:
    """Fetch realized funding for each ticker over ``[start_ts, end_ts]`` and
    persist every settlement not already stored.

    Idempotent: a second run over an overlapping window writes only the new
    rows. One ticker's request failure is logged and counted; the others
    still run.
    """
    result = FundingBackfillResult(tickers=tuple(tickers))
    fetched_at = int(time.time())

    for ticker in tickers:
        try:
            body = client.get_historical_funding_rates(
                ticker=ticker, start_ts=start_ts, end_ts=end_ts
            )
        except Exception as exc:  # one ticker down must not stop the rest
            result.errors += 1
            logger.warning("funding backfill: {} request failed: {}", ticker, exc)
            continue

        rows = body.get("funding_rates", []) if isinstance(body, dict) else []
        if not isinstance(rows, list):
            result.errors += 1
            logger.warning("funding backfill: {} returned no funding_rates list", ticker)
            continue

        already = _existing_observed_at(session, ticker)
        pending = 0
        for row in rows:
            if not isinstance(row, dict):
                result.malformed_skipped += 1
                continue
            result.rows_seen += 1
            observed_at = _parse_funding_time(row.get("funding_time"))
            rate = row.get("funding_rate")
            if observed_at is None or not isinstance(rate, (int, float)) or isinstance(rate, bool):
                result.malformed_skipped += 1
                continue
            if not (start_ts <= observed_at <= end_ts):
                # Outside the asked window; ignore rather than store noise.
                continue
            if observed_at in already:
                result.duplicates_skipped += 1
                continue

            mark = row.get("mark_price")
            session.add(
                PerpFundingObservation(
                    market_ticker=ticker,
                    observed_at=observed_at,
                    available_at=observed_at,
                    funding_rate=float(rate),
                    mark_price_dollars=str(mark) if mark is not None else None,
                    source=SOURCE_LABEL,
                    capture_session_id=session_id,
                    source_endpoint=ENDPOINT,
                    fetched_at=fetched_at,
                    provenance={"operator_run": True, "backfill_window": [start_ts, end_ts]},
                )
            )
            already.add(observed_at)
            pending += 1
            result.persisted += 1
            result.first_observed_at = (
                observed_at
                if result.first_observed_at is None
                else min(result.first_observed_at, observed_at)
            )
            result.last_observed_at = (
                observed_at
                if result.last_observed_at is None
                else max(result.last_observed_at, observed_at)
            )

        if pending:
            session.commit()
            logger.info("funding backfill: {} +{} rows", ticker, pending)

    session.commit()
    logger.info("funding backfill finished: {}", result.as_dict())
    return result


class NoCryptoPerpsMatchedError(RuntimeError):
    """Raised when ``resolve_crypto_perp_tickers`` finds zero matches.

    A silent empty list here previously made every downstream capture
    (funding backfill, mark polling, funding-estimate snapshots) look like a
    clean no-op run instead of a broken resolution -- Kalshi's demo
    environment renumbered every crypto perp ticker (``KXBTCPERP`` ->
    ``KXBTCPERP1``, etc.) and capture kept "succeeding" with zero new rows
    for days before anyone noticed. Failing loudly here is deliberate: a
    ticker-shape change on the exchange side must stop the capture script,
    not degrade it into a silent no-op.
    """


# Kalshi's ticker suffix after the asset symbol and before an optional
# version digit, e.g. "KXBTCPERP" or "KXBTCPERP1". A bare digit suffix is
# treated as instrument versioning by the exchange, not a different asset --
# but it CAN mean a different contract size/notional (observed: demo's
# ``KXBTCPERP1`` replaced ``KXBTCPERP`` with a 0.0001 BTC/contract reissue).
# Capture records whichever ticker shape is actually live; it does not
# assume version N and N+1 are numerically comparable.
_PERP_TICKER_RE = re.compile(r"^KX(?P<symbol>[A-Z]+)PERP(?P<version>\d*)$")


def resolve_crypto_perp_tickers(
    client: _FundingClient, *, wanted: Iterable[str] | None = None
) -> list[str]:
    """List active crypto-perp market tickers from ``/margin/markets``.

    ``wanted`` optionally filters to a set of asset symbols (e.g. ``{"BTC",
    "ETH"}`` -> ``["KXBTCPERP", "KXETHPERP"]``, or whatever versioned ticker
    the exchange currently lists for that symbol, e.g. ``KXBTCPERP1``).  With
    no filter, every active ``asset_class == "Crypto"`` perp is returned.

    Raises :class:`NoCryptoPerpsMatchedError` if ``wanted`` is given and
    nothing active matches any requested symbol -- see that class's
    docstring for why this must not degrade into an empty list.
    """
    body = client.get_markets(status="active")
    markets = body.get("markets", []) if isinstance(body, dict) else []
    wanted_upper = {w.upper() for w in wanted} if wanted is not None else None
    out: list[str] = []
    for m in markets:
        if not isinstance(m, dict):
            continue
        ticker = str(m.get("ticker", ""))
        match = _PERP_TICKER_RE.match(ticker)
        if match is None:
            continue
        if str(m.get("asset_class", "")).lower() != "crypto":
            continue
        if wanted_upper is not None and match.group("symbol") not in wanted_upper:
            continue
        out.append(ticker)
    if wanted_upper is not None and not out:
        raise NoCryptoPerpsMatchedError(
            f"no active crypto perps matched {sorted(wanted_upper)}; the exchange "
            "may have renumbered or delisted these tickers -- check "
            "GET /margin/markets?status=active for the current ticker shape "
            "before assuming this is a transient outage"
        )
    return out


__all__ = [
    "ENDPOINT",
    "ESTIMATE_ENDPOINT",
    "ESTIMATE_SOURCE_LABEL",
    "SOURCE_LABEL",
    "FundingBackfillResult",
    "FundingEstimateCaptureResult",
    "NoCryptoPerpsMatchedError",
    "backfill_funding",
    "capture_funding_estimates",
    "resolve_crypto_perp_tickers",
]
