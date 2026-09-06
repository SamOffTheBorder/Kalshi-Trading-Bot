"""Authenticated Kalshi client (spec: kalshi-authenticated-api, tasks.md §4).

Every private endpoint requires an RSA-PSS signature over
`timestamp_ms + method + path` (path only, no query string), sent as
`KALSHI-ACCESS-SIGNATURE` alongside `KALSHI-ACCESS-KEY` and
`KALSHI-ACCESS-TIMESTAMP` headers. There is no unauthenticated path for any
`/portfolio`, `/orders`, or `/margin` endpoint — unlike the public market-data
client (`data/kalshi/client.py`), this one cannot do anything with zero
credentials.

Read-only endpoints (tasks.md 4.2): balance, positions, fills, orders —
smoke-tested live against production (see tasks.md for details).

Order placement (tasks.md 4.3): `create_order`/`cancel_order`/`amend_order`.
As of this change these are implemented and unit-tested against mocked HTTP
only — **no live call has been made against demo or production**. That is a
deliberate, separate step requiring its own explicit go-ahead.

Demo vs. prod is controlled by `Settings.kalshi_use_demo_env`, not a
constructor default, so which environment a call hits is never a silent
accident of forgetting an argument.
"""

from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from loguru import logger

PROD_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
DEMO_BASE_URL = "https://demo-api.kalshi.co/trade-api/v2"

LIVE_TRADING_CONFIRMATION_PHRASE = "I understand this places real orders"
"""The exact phrase `Settings.live_trading_confirmation_phrase` must equal
(case-sensitive) before `_guard_live_order` will allow paper_trading=False
against production. Shared here so client and settings can't drift apart on
what the required phrase actually is."""


class KalshiAuthError(Exception):
    """401/403 from the API — never retried."""


def load_private_key(path: Path) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise TypeError(f"{path} is not an RSA private key")
    return key


def sign_request(private_key: rsa.RSAPrivateKey, timestamp_ms: str, method: str, path: str) -> str:
    """Sign `timestamp_ms + method + path` per Kalshi's RSA-PSS scheme.

    `path` must be the request path only (e.g. `/trade-api/v2/portfolio/balance`),
    no query string, no host.
    """
    message = f"{timestamp_ms}{method}{path}".encode()
    signature = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode()


class KalshiConfigError(Exception):
    """Raised before any network request when the client is misconfigured
    in a way that could otherwise place a real order somewhere unintended."""


class KalshiAuthenticatedClient:
    def __init__(
        self,
        *,
        key_id: str,
        private_key_path: Path,
        use_demo_env: bool = True,
        paper_trading: bool = True,
        live_trading_confirmation_phrase: str | None = None,
        max_reads_per_second: int = 8,
        max_retries: int = 4,
        timeout_s: float = 15.0,
    ) -> None:
        self._key_id = key_id
        self._private_key = load_private_key(private_key_path)
        self._use_demo_env = use_demo_env
        self._paper_trading = paper_trading
        self._live_trading_confirmation_phrase = live_trading_confirmation_phrase
        self._base_url = DEMO_BASE_URL if use_demo_env else PROD_BASE_URL
        self._api_prefix = "/trade-api/v2"
        self._client = httpx.Client(base_url=self._base_url, timeout=timeout_s)
        self._max_retries = max_retries
        self._max_reads_per_second = max_reads_per_second
        self._last_call_monotonic = 0.0

        logger.info(
            "KalshiAuthenticatedClient: {} environment ({}), paper_trading={}",
            "DEMO" if use_demo_env else "PRODUCTION",
            self._base_url,
            paper_trading,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> KalshiAuthenticatedClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transport -----------------------------------------------------------

    def _headers(self, method: str, path: str) -> dict[str, str]:
        timestamp_ms = str(int(time.time() * 1000))
        full_path = f"{self._api_prefix}{path}"
        signature = sign_request(self._private_key, timestamp_ms, method, full_path)
        return {
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        }

    def _throttle(self) -> None:
        min_interval = 1.0 / self._max_reads_per_second
        elapsed = time.monotonic() - self._last_call_monotonic
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_call_monotonic = time.monotonic()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        backoff = 1.0
        for attempt in range(1, self._max_retries + 1):
            self._throttle()
            response = self._client.get(path, params=params, headers=self._headers("GET", path))
            if response.status_code in (401, 403):
                raise KalshiAuthError(f"{response.status_code} on {path}: {response.text[:300]}")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self._max_retries:
                    response.raise_for_status()
                logger.warning(
                    "Kalshi {} on {} (attempt {}/{}), backing off {:.1f}s",
                    response.status_code,
                    path,
                    attempt,
                    self._max_retries,
                    backoff,
                )
                time.sleep(backoff)
                backoff *= 2
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError("unreachable")  # pragma: no cover

    def _request(
        self, method: Literal["POST", "DELETE"], path: str, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        backoff = 1.0
        for attempt in range(1, self._max_retries + 1):
            self._throttle()
            response = self._client.request(
                method, path, json=json_body, headers=self._headers(method, path)
            )
            if response.status_code in (401, 403):
                raise KalshiAuthError(f"{response.status_code} on {path}: {response.text[:300]}")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self._max_retries:
                    response.raise_for_status()
                logger.warning(
                    "Kalshi {} on {} {} (attempt {}/{}), backing off {:.1f}s",
                    response.status_code,
                    method,
                    path,
                    attempt,
                    self._max_retries,
                    backoff,
                )
                time.sleep(backoff)
                backoff *= 2
                continue
            response.raise_for_status()
            return response.json() if response.content else {}
        raise RuntimeError("unreachable")  # pragma: no cover

    # -- read-only account/portfolio endpoints (tasks.md 4.2) -----------------

    def get_balance(self) -> dict[str, Any]:
        return self._get("/portfolio/balance")

    def get_positions(
        self,
        *,
        ticker: str | None = None,
        event_ticker: str | None = None,
        settlement_status: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        if settlement_status:
            params["settlement_status"] = settlement_status
        if cursor:
            params["cursor"] = cursor
        return self._get("/portfolio/positions", params)

    def get_fills(
        self,
        *,
        ticker: str | None = None,
        order_id: str | None = None,
        min_ts: int | None = None,
        max_ts: int | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if order_id:
            params["order_id"] = order_id
        if min_ts is not None:
            params["min_ts"] = min_ts
        if max_ts is not None:
            params["max_ts"] = max_ts
        if cursor:
            params["cursor"] = cursor
        return self._get("/portfolio/fills", params)

    def get_orders(
        self,
        *,
        ticker: str | None = None,
        event_ticker: str | None = None,
        status: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        return self._get("/portfolio/orders", params)

    # -- order placement (tasks.md 4.3) ---------------------------------------
    #
    # Untested against any live environment (demo or prod) as of this change —
    # unit tests here use mocked HTTP only. A live smoke test against demo is
    # a required, separate, explicit step before this is ever used for real.

    def _guard_live_order(self) -> None:
        if not self._use_demo_env and self._paper_trading:
            raise KalshiConfigError(
                "Refusing to place/amend an order against PRODUCTION while "
                "paper_trading=True. This combination is always a "
                "misconfiguration — either point at the demo environment, or "
                "set paper_trading=False to confirm you intend a live order."
            )
        if (
            not self._use_demo_env
            and not self._paper_trading
            and self._live_trading_confirmation_phrase != LIVE_TRADING_CONFIRMATION_PHRASE
        ):
            raise KalshiConfigError(
                "Refusing to place/amend an order against PRODUCTION: "
                "paper_trading=False but live_trading_confirmation_phrase does not "
                f"match the required phrase ({LIVE_TRADING_CONFIRMATION_PHRASE!r}). "
                "Set Settings.live_trading_confirmation_phrase to that exact phrase "
                "to confirm you intend real orders — this is a deliberate typing "
                "exercise, not a UI toggle, so live trading can never turn on by "
                "flipping one boolean."
            )

    def create_order(
        self,
        *,
        market_ticker: str,
        side: Literal["yes", "no"],
        action: Literal["buy", "sell"],
        count: int,
        order_type: Literal["market", "limit"] = "limit",
        yes_price_cents: int | None = None,
        no_price_cents: int | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Place an order. Kalshi requires exactly one of `yes_price_cents` /
        `no_price_cents` for a limit order (whichever side's price you're
        quoting); neither for a market order. `client_order_id` defaults to a
        fresh UUID so retries by the caller can't accidentally double-submit
        under a repeated id — every call places at most one new order unless
        the caller deliberately reuses an id.

        Raises `KalshiConfigError` before any network request if this client
        is pointed at production while `paper_trading` is true (spec:
        kalshi-authenticated-api "Demo and production environments are
        structurally distinct") — that combination is always a
        misconfiguration, never something to attempt with a fallback."""
        self._guard_live_order()
        if order_type == "limit" and yes_price_cents is None and no_price_cents is None:
            raise ValueError("limit orders require yes_price_cents or no_price_cents")
        body: dict[str, Any] = {
            "ticker": market_ticker,
            "side": side,
            "action": action,
            "count": count,
            "type": order_type,
            "client_order_id": client_order_id or str(uuid.uuid4()),
        }
        if yes_price_cents is not None:
            body["yes_price"] = yes_price_cents
        if no_price_cents is not None:
            body["no_price"] = no_price_cents
        return self._request("POST", "/portfolio/orders", body)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/portfolio/orders/{order_id}")

    def amend_order(
        self,
        order_id: str,
        *,
        count: int,
        yes_price_cents: int | None = None,
        no_price_cents: int | None = None,
    ) -> dict[str, Any]:
        """Amend a resting order's quantity/price. Kalshi implements amend as
        an atomic decrease-and-optionally-reprice; it does not support
        increasing quantity (cancel and place a new order for that).

        Same production/paper_trading guard as `create_order` — see there."""
        self._guard_live_order()
        body: dict[str, Any] = {"count": count}
        if yes_price_cents is not None:
            body["yes_price"] = yes_price_cents
        if no_price_cents is not None:
            body["no_price"] = no_price_cents
        return self._request("POST", f"/portfolio/orders/{order_id}/amend", body)


__all__ = [
    "LIVE_TRADING_CONFIRMATION_PHRASE",
    "KalshiAuthError",
    "KalshiAuthenticatedClient",
    "KalshiConfigError",
    "load_private_key",
    "sign_request",
]
