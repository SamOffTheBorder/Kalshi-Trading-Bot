import hashlib
from pathlib import Path

import httpx
import pytest

from kalshi_bot.data.external_sources import (
    binance_instrument,
    kraken_constituent_instrument,
)
from kalshi_bot.data.kraken_public import (
    KrakenArchiveError,
    KrakenPublicClient,
    archive_artifact,
    raw_artifact_provenance,
)


def test_kraken_archive_path_is_a_single_cumulative_csv_per_pair():
    artifact = archive_artifact(kraken_constituent_instrument("BTC"))
    assert artifact.filename == "BTCUSD.csv"
    assert artifact.url.endswith("/BTCUSD.csv")


def test_archive_builder_requires_a_constituent_kraken_instrument():
    with pytest.raises(KrakenArchiveError, match="constituent"):
        archive_artifact(binance_instrument("BTC", "spot"))


def test_download_is_atomic_and_idempotent(tmp_path: Path):
    payload = b"price,volume,time\n100,1,1000\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    transport = httpx.MockTransport(handler)
    client = KrakenPublicClient(client=httpx.Client(transport=transport))
    artifact = archive_artifact(kraken_constituent_instrument("BTC"))
    destination = tmp_path / "BTCUSD.csv"

    digest = client.download(artifact, destination)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert destination.read_bytes() == payload
    assert not destination.with_suffix(".csv.part").exists()

    # Idempotent resume: a second call with a transport that would error if
    # hit must not touch the network because the destination already exists.
    def failing_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not re-fetch an already-downloaded artifact")

    client2 = KrakenPublicClient(
        client=httpx.Client(transport=httpx.MockTransport(failing_handler))
    )
    digest2 = client2.download(artifact, destination)
    assert digest2 == digest


def test_raw_artifact_provenance_is_always_unverified():
    artifact = archive_artifact(kraken_constituent_instrument("BTC"))
    provenance = raw_artifact_provenance(
        artifact, content_sha256="a" * 64, byte_size=123, retrieved_at=1_000
    )
    assert provenance.checksum_status == "unverified"
    assert provenance.source == "kraken"
    assert provenance.source_role == "constituent"
    assert provenance.quote_currency == "USD"
    assert provenance.source_url == artifact.url
