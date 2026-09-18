"""Read-only Kraken public historical-trade archive access.

Kraken publishes complete USD trade history per pair as direct CSV downloads
and publishes no sidecar checksum for them. Every artifact retrieved here is
therefore recorded honestly as unverified -- never as checksum-verified.

**BASE_URL is UNVERIFIED.** `data.kraken.com` does not resolve (confirmed by
DNS lookup during this change's own verification pass, tasks.md 9.5 -- this
is not a sandbox network restriction; kraken.com itself and the general
internet were reachable). Kraken's real historical-trade distribution is
described at
https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data
which is sign-in-gated and appears to point at a cloud-storage bucket not
discoverable by static scraping. An operator MUST confirm the real download
URL (and re-verify the archive shape `normalize_kraken_trades` assumes --
``price, volume, time[, ...]`` CSV rows) against that page before the first
real backfill run. `KrakenPublicClient`/`archive_artifact` are exercised
only against fixtures and a mocked transport in this codebase's test suite;
none of it has run against Kraken's actual endpoint.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import httpx

from kalshi_bot.data.external_sources import ExternalInstrument

BASE_URL = "https://data.kraken.com/csv"  # UNVERIFIED -- see module docstring


class KrakenArchiveError(RuntimeError):
    """Raised when a Kraken archive reference or download is invalid."""


@dataclass(frozen=True)
class KrakenArchiveArtifact:
    instrument: ExternalInstrument
    filename: str
    url: str


@dataclass(frozen=True)
class RawArtifactProvenance:
    """Fields a caller persists into ``RawMarketArtifact`` for one download.

    Kraken publishes no sidecar checksum, so ``checksum_status`` is always
    ``"unverified"`` here -- never ``"verified"`` for a Kraken artifact.
    """

    source: str
    source_role: str
    venue: str
    native_symbol: str
    market_type: str
    quote_currency: str
    content_sha256: str
    byte_size: int
    source_url: str
    retrieved_at: int
    checksum_status: str
    parser_version: str


def archive_artifact(instrument: ExternalInstrument) -> KrakenArchiveArtifact:
    """Build a reference to Kraken's full trade-history CSV for a pair.

    Kraken publishes one cumulative CSV per pair rather than per-day/month
    archives, so there is no year/month/day partitioning to build.
    """

    if instrument.source != "kraken" or instrument.source_role != "constituent":
        raise KrakenArchiveError("archive builder requires a constituent Kraken instrument")
    filename = f"{instrument.native_symbol}.csv"
    return KrakenArchiveArtifact(
        instrument=instrument,
        filename=filename,
        url=f"{BASE_URL}/{filename}",
    )


class KrakenPublicClient:
    """Bounded foreground downloader for public Kraken archives only."""

    def __init__(self, *, timeout_s: float = 30.0, client: httpx.Client | None = None) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._client = client or httpx.Client(timeout=timeout_s, follow_redirects=True)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> KrakenPublicClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def download(self, artifact: KrakenArchiveArtifact, destination: Path) -> str:
        """Download one archive and atomically cache it.

        Idempotent and resumable: if ``destination`` already holds content
        matching a prior successful download, no network request is made and
        the existing content hash is returned. Kraken publishes no checksum,
        so integrity is always recorded as unverified by the caller.
        """

        if destination.exists():
            return hashlib.sha256(destination.read_bytes()).hexdigest()
        response = self._client.get(artifact.url)
        response.raise_for_status()
        digest = hashlib.sha256(response.content).hexdigest()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.write_bytes(response.content)
        temporary.replace(destination)
        return digest


def raw_artifact_provenance(
    artifact: KrakenArchiveArtifact,
    *,
    content_sha256: str,
    byte_size: int,
    retrieved_at: int,
    parser_version: str = "kraken-trade-v1",
) -> RawArtifactProvenance:
    """Build the honest, unverified provenance record for one download."""

    instrument = artifact.instrument
    return RawArtifactProvenance(
        source=instrument.source,
        source_role=instrument.source_role,
        venue=instrument.venue,
        native_symbol=instrument.native_symbol,
        market_type=instrument.market_type,
        quote_currency=instrument.quote_currency,
        content_sha256=content_sha256,
        byte_size=byte_size,
        source_url=artifact.url,
        retrieved_at=retrieved_at,
        checksum_status="unverified",
        parser_version=parser_version,
    )


__all__ = [
    "BASE_URL",
    "KrakenArchiveArtifact",
    "KrakenArchiveError",
    "KrakenPublicClient",
    "RawArtifactProvenance",
    "archive_artifact",
    "raw_artifact_provenance",
]
