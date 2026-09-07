"""BRTI source: Kalshi's authenticated CF Benchmarks REST passthrough.

There is no free or anonymous BRTI feed. CF Benchmarks licenses the index;
the only route this project has is Kalshi's passthrough, which re-exposes the
CF Benchmarks REST API to an authenticated Kalshi account:

    GET https://external-api.kalshi.com/trade-api/v2/cfbenchmarks/values?id=BRTI
    (RSA-PSS signed over  <ts_ms> + "GET" + "/trade-api/v2/cfbenchmarks/values")

Note the host is `external-api.kalshi.com`, NOT the `api.elections.kalshi.com`
that `execution/kalshi_client.py` uses for portfolio/order endpoints — the
passthrough lives on its own gateway. Signing scheme and key are identical, so
`sign_request` / `load_private_key` are reused.

This is a **read-only market-data** call. It touches no `/portfolio`,
`/orders`, or `/margin` path and can place nothing. The operator has approved
using it for continuous foreground BRTI capture; `poll_brti` (see `poll.py`)
drives it once per interval.

The upstream CF Benchmarks payload under `data` carries, per the docs:

    {"type": "value", "id": "BRTI", "time": <ms since epoch>, "value": "<price>"}

`time` is when the index value refers to. The passthrough adds a `serverTime`
(ISO-8601) at the top level; we take local receipt time as `available_at`
since that is the instant this process could first act on the number, and it
is never earlier than `time`.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.asymmetric import rsa
from loguru import logger

from kalshi_bot.data.brti.poll import BRTIReadingRaw
from kalshi_bot.execution.kalshi_client import load_private_key, sign_request

PASSTHROUGH_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
VALUES_PATH = "/cfbenchmarks/values"
SIGNING_PATH = "/trade-api/v2/cfbenchmarks/values"
DEFAULT_INDEX_ID = "BRTI"


class KalshiBRTISource:
    """`BRTISource` backed by Kalshi's CF Benchmarks passthrough.

    `fetch()` returns the latest reading, or `None` on a transient error
    (timeout, 5xx, a malformed payload) so `poll_brti` treats it as a skipped
    tick rather than crashing the capture. An auth failure (401/403) DOES
    raise — a bad key is not transient and silently dropping every tick for
    90 days would be worse than stopping.
    """

    name = "kalshi:cfbenchmarks/BRTI"

    def __init__(
        self,
        *,
        key_id: str,
        private_key_path: Path,
        index_id: str = DEFAULT_INDEX_ID,
        timeout_s: float = 10.0,
        base_url: str = PASSTHROUGH_BASE_URL,
        _private_key: rsa.RSAPrivateKey | None = None,
        _client: httpx.Client | None = None,
    ) -> None:
        self._key_id = key_id
        self._private_key = _private_key or load_private_key(private_key_path)
        self._index_id = index_id
        self._client = _client or httpx.Client(base_url=base_url, timeout=timeout_s)
        self.name = f"kalshi:cfbenchmarks/{index_id}"

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> KalshiBRTISource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        ts_ms = str(int(time.time() * 1000))
        return {
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-SIGNATURE": sign_request(self._private_key, ts_ms, "GET", SIGNING_PATH),
            "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        }

    def fetch(self) -> BRTIReadingRaw | None:
        try:
            resp = self._client.get(
                VALUES_PATH, params={"id": self._index_id}, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            logger.warning("BRTI passthrough request failed: {}", exc)
            return None

        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"BRTI passthrough auth failed ({resp.status_code}): {resp.text[:200]}. "
                "Check KALSHI_KEY_ID and secrets/kalshi_private_key.pem, and that the "
                "account has CF Benchmarks passthrough access."
            )
        if resp.status_code != 200:
            logger.warning("BRTI passthrough {} : {}", resp.status_code, resp.text[:200])
            return None

        try:
            body = resp.json()
        except ValueError:
            logger.warning("BRTI passthrough returned non-JSON body")
            return None

        return _parse_values_payload(body, source=self.name)


def _parse_values_payload(body: object, *, source: str) -> BRTIReadingRaw | None:
    """Pull one reading out of the passthrough response.

    Shape (per the Kalshi + CF Benchmarks docs):
        {"data": {"serverTime": "...ISO...",
                  "payload": {"type": "value", "id": "BRTI",
                              "time": <ms>, "value": "<price>"}}}
    Some CF Benchmarks responses nest the value list differently; this walks
    the common shapes and returns None (a skipped tick) rather than raising if
    none match.
    """
    if not isinstance(body, dict):
        return None
    data = body.get("data", body)
    if not isinstance(data, dict):
        return None

    payload = data.get("payload", data)
    candidates: list[dict[str, object]] = []
    if isinstance(payload, dict):
        if "value" in payload and ("time" in payload or "timestamp" in payload):
            candidates.append(payload)
        # e.g. {"payload": {"values": [ {..}, {..} ]}}
        vals = payload.get("values")
        if isinstance(vals, list):
            candidates.extend(v for v in vals if isinstance(v, dict))
    if isinstance(payload, list):
        candidates.extend(v for v in payload if isinstance(v, dict))

    for item in candidates:
        raw_value = item.get("value")
        raw_time = item.get("time", item.get("timestamp"))
        if not isinstance(raw_value, (str, int, float)):
            continue
        if not isinstance(raw_time, (str, int, float)):
            continue
        try:
            value = float(raw_value)
            observed_ms = int(float(raw_time))
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        return BRTIReadingRaw(
            observed_at=observed_ms // 1000,
            value=value,
            source=source,
            available_at=None,  # poll_brti stamps local receipt time
            extra={"index_id": str(item.get("id", "")), "observed_at_ms": observed_ms},
        )
    return None


__all__ = ["PASSTHROUGH_BASE_URL", "SIGNING_PATH", "VALUES_PATH", "KalshiBRTISource"]
