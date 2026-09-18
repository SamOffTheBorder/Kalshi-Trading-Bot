"""Read-only Binance public archive access with checksum verification."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from kalshi_bot.data.external_sources import ExternalInstrument

BASE_URL = "https://data.binance.vision/data"
_CHECKSUM_RE = re.compile(r"(?P<hash>[0-9a-fA-F]{64})\s+(?P<name>\S+)")


class BinanceArchiveError(RuntimeError):
    """Raised when a public archive cannot be safely verified."""


@dataclass(frozen=True)
class ArchiveArtifact:
    instrument: ExternalInstrument
    dataset: str
    interval: str
    filename: str
    url: str
    checksum_url: str


def archive_artifact(
    instrument: ExternalInstrument,
    *,
    dataset: str,
    interval: str,
    year: int,
    month: int,
    day: int | None = None,
) -> ArchiveArtifact:
    """Build a Binance daily/monthly archive reference without fetching it."""

    if instrument.source != "binance" or instrument.source_role != "primary":
        raise BinanceArchiveError("archive builder requires a primary Binance instrument")
    if dataset not in {"klines", "aggTrades"}:
        raise BinanceArchiveError(f"unsupported Binance dataset: {dataset!r}")
    if not 1 <= month <= 12 or year < 2017:
        raise BinanceArchiveError("invalid archive year/month")
    if day is None:
        period = f"{year:04d}-{month:02d}"
        filename = f"{instrument.native_symbol}-{interval}-{period}.zip"
        root = (
            f"{instrument.archive_family}/monthly/{dataset}/"
            f"{instrument.native_symbol}/{interval}"
        )
    else:
        if not 1 <= day <= 31:
            raise BinanceArchiveError("invalid archive day")
        period = f"{year:04d}-{month:02d}-{day:02d}"
        filename = f"{instrument.native_symbol}-{interval}-{period}.zip"
        root = f"{instrument.archive_family}/daily/{dataset}/{instrument.native_symbol}/{interval}"
    url = f"{BASE_URL}/{root}/{filename}"
    return ArchiveArtifact(
        instrument=instrument,
        dataset=dataset,
        interval=interval,
        filename=filename,
        url=url,
        checksum_url=f"{url}.CHECKSUM",
    )


def verify_checksum(payload: bytes, checksum_text: str, *, filename: str) -> str:
    """Verify a Binance ``.CHECKSUM`` payload and return its SHA-256 hash."""

    expected: str | None = None
    for line in checksum_text.splitlines():
        match = _CHECKSUM_RE.search(line.strip())
        if match and match.group("name").lstrip("*") == filename:
            expected = match.group("hash").lower()
            break
    if expected is None:
        raise BinanceArchiveError(f"checksum file has no entry for {filename}")
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise BinanceArchiveError(
            f"checksum mismatch for {filename}: expected {expected}, got {actual}"
        )
    return actual


class BinancePublicClient:
    """Bounded foreground downloader for public archive artifacts only."""

    def __init__(self, *, timeout_s: float = 30.0, client: httpx.Client | None = None) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._client = client or httpx.Client(timeout=timeout_s, follow_redirects=True)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> BinancePublicClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def download_verified(self, artifact: ArchiveArtifact, destination: Path) -> str:
        """Download one archive and checksum, then atomically cache it."""

        response = self._client.get(artifact.url)
        response.raise_for_status()
        checksum = self._client.get(artifact.checksum_url)
        checksum.raise_for_status()
        digest = verify_checksum(response.content, checksum.text, filename=artifact.filename)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.write_bytes(response.content)
        temporary.replace(destination)
        return digest


__all__ = [
    "BASE_URL",
    "ArchiveArtifact",
    "BinanceArchiveError",
    "BinancePublicClient",
    "archive_artifact",
    "verify_checksum",
]
