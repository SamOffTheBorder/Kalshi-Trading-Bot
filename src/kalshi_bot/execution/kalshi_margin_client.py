"""Kalshi margin (perps) client (spec: kalshi-authenticated-api, tasks.md §4.4).

All `/margin/*` endpoints live under the same base URL, RSA-PSS signing
scheme, and rate-limit/retry behavior as `KalshiAuthenticatedClient`'s
`/portfolio/*` endpoints — confirmed against `docs.kalshi.com`: e.g.
`GET {base}/trade-api/v2/margin/positions`, not a separate `margin-rest` host
(tasks.md 1.4's note about `/margin-rest/*` paths refers to the doc site's
*documentation* URL structure, not actual API paths — verified 2026-09-06).
This client is a thin sibling to `KalshiAuthenticatedClient` rather than a
subclass of it, since the two cover distinct instrument types (event
contracts vs. perps) that never share a call site.

Prices in the margin API are dollar strings (e.g. "0.4500"), not integer
cents like the event-contract API — Kalshi's own docs represent them as
`FixedPointDollars` strings. Methods here pass amounts through as `str` to
avoid float-precision surprises; callers convert as needed.

Read-only endpoints only (markets, orderbook, positions, balance, risk,
funding). Order placement (`create_order`) is implemented and unit-tested
against mocked HTTP only — **no live call has been made against demo or
production** — same discipline as `KalshiAuthenticatedClient.create_order`,
including the identical prod+paper_trading guard.

Exit-trigger (stop-loss/take-profit bracket and trailing-stop) endpoints
(tasks.md 4.5) are implemented below for both isolated and cross margin
positions — this is the auto-stop-loss mechanism: brackets live server-side
so a crashed bot cannot orphan a leveraged position. Verified against
`docs.kalshi.com/margin-rest/exit-triggers/*` 2026-09-06. Mutating calls
(`set_*`/`update_*`/`cancel_*`) go through the same `_guard_live_order()`
prod+paper_trading interlock as `create_order` — mocked HTTP unit tests
only, no live call made against demo or production.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx
from loguru import logger

from kalshi_bot.execution.kalshi_client import (
    DEMO_BASE_URL,
    LIVE_TRADING_CONFIRMATION_PHRASE,
    PROD_BASE_URL,
    KalshiAuthError,
    KalshiConfigError,
    load_private_key,
    sign_request,
)

Side = Literal["bid", "ask"]
TimeInForce = Literal["fill_or_kill", "good_till_canceled", "immediate_or_cancel"]
ExitTriggerKind = Literal["bracket", "trailing"]


class KalshiMarginClient:
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
            "KalshiMarginClient: {} environment ({}), paper_trading={}",
            "DEMO" if use_demo_env else "PRODUCTION",
            self._base_url,
            paper_trading,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> KalshiMarginClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transport (identical pattern to KalshiAuthenticatedClient) ----------

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

    def _post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any]:
        backoff = 1.0
        for attempt in range(1, self._max_retries + 1):
            self._throttle()
            response = self._client.post(path, json=json_body, headers=self._headers("POST", path))
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
            return response.json() if response.content else {}
        raise RuntimeError("unreachable")  # pragma: no cover

    def _request(
        self,
        method: Literal["PUT", "DELETE"],
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        backoff = 1.0
        for attempt in range(1, self._max_retries + 1):
            self._throttle()
            response = self._client.request(
                method, path, params=params, json=json_body, headers=self._headers(method, path)
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

    def _guard_live_order(self) -> None:
        if not self._use_demo_env and self._paper_trading:
            raise KalshiConfigError(
                "Refusing to place a margin order against PRODUCTION while "
                "paper_trading=True. Point at the demo environment, or set "
                "paper_trading=False to confirm you intend a live order."
            )
        if (
            not self._use_demo_env
            and not self._paper_trading
            and self._live_trading_confirmation_phrase != LIVE_TRADING_CONFIRMATION_PHRASE
        ):
            raise KalshiConfigError(
                "Refusing to place a margin order against PRODUCTION: "
                "paper_trading=False but live_trading_confirmation_phrase does not "
                f"match the required phrase ({LIVE_TRADING_CONFIRMATION_PHRASE!r}). "
                "Set Settings.live_trading_confirmation_phrase to that exact phrase "
                "to confirm you intend real orders."
            )

    # -- markets ---------------------------------------------------------------

    def get_markets(self, *, status: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if status:
            params["status"] = status
        return self._get("/margin/markets", params)

    def get_market(self, ticker: str) -> dict[str, Any]:
        return self._get(f"/margin/markets/{ticker}")

    def get_market_orderbook(
        self, ticker: str, *, depth: int | None = None, aggregation_tick_size: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if depth is not None:
            params["depth"] = depth
        if aggregation_tick_size is not None:
            params["aggregation_tick_size"] = aggregation_tick_size
        return self._get(f"/margin/markets/{ticker}/orderbook", params)

    # -- positions / balance / risk --------------------------------------------

    def get_positions(
        self, *, subaccount: int | None = None, ticker: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if subaccount is not None:
            params["subaccount"] = subaccount
        if ticker:
            params["ticker"] = ticker
        return self._get("/margin/positions", params)

    def get_balance(self, *, compute_available_balance: bool = False) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if compute_available_balance:
            params["compute_available_balance"] = True
        return self._get("/margin/balance", params)

    def get_risk(self) -> dict[str, Any]:
        return self._get("/margin/risk")

    def get_risk_parameters(self) -> dict[str, Any]:
        return self._get("/margin/risk/parameters")

    def get_notional_risk_limit(self) -> dict[str, Any]:
        return self._get("/margin/risk/notional-limit")

    # -- funding -----------------------------------------------------------------

    def get_funding_rate_estimate(self, ticker: str) -> dict[str, Any]:
        return self._get("/margin/funding_rates/estimate", {"ticker": ticker})

    def get_historical_funding_rates(
        self,
        *,
        ticker: str | None = None,
        start_ts: int | None = None,
        end_ts: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if ticker:
            params["ticker"] = ticker
        if start_ts is not None:
            params["start_ts"] = start_ts
        if end_ts is not None:
            params["end_ts"] = end_ts
        return self._get("/margin/funding_rates/historical", params)

    # -- order placement (tasks.md 4.4) ---------------------------------------
    #
    # Untested against any live environment (demo or prod) — mocked HTTP unit
    # tests only. A live smoke test against demo is a required, separate,
    # explicit step before this is ever used for real.

    def create_order(
        self,
        *,
        market_ticker: str,
        side: Side,
        count: str,
        price: str,
        time_in_force: TimeInForce = "good_till_canceled",
        post_only: bool = True,
        reduce_only: bool = False,
        subaccount: int | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Place a margin (perps) order. `count` and `price` are Kalshi
        fixed-point dollar/contract strings, not floats — avoids
        float-precision drift on the wire.

        `post_only=True` by default (spec: kalshi-authenticated-api
        "Maker-preferred order placement" — resting, not marketable, since
        maker fees are ~1/4 of taker). Same prod+paper_trading guard as
        `KalshiAuthenticatedClient.create_order`.
        """
        self._guard_live_order()
        body: dict[str, Any] = {
            "ticker": market_ticker,
            "side": side,
            "count": count,
            "price": price,
            "time_in_force": time_in_force,
            "post_only": post_only,
            "reduce_only": reduce_only,
            "client_order_id": client_order_id or str(uuid.uuid4()),
        }
        if subaccount is not None:
            body["subaccount"] = subaccount
        return self._post("/margin/orders", body)

    # -- exit triggers: isolated positions (tasks.md 4.5) -----------------------
    #
    # A crashed bot must not be able to orphan a leveraged position — these
    # brackets/trailing stops live server-side on the exchange, not in this
    # process. Mutating calls share create_order's prod+paper_trading guard.

    def get_isolated_exit_triggers(
        self, ticker: str, *, kind: ExitTriggerKind | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if kind is not None:
            params["kind"] = kind
        return self._get(f"/margin/isolated/positions/{ticker}/exit_trigger", params)

    def set_isolated_exit_trigger(
        self,
        ticker: str,
        *,
        kind: ExitTriggerKind = "bracket",
        stop_loss_price: str | None = None,
        take_profit_price: str | None = None,
        trail_amount: str | None = None,
        trail_bps: int | None = None,
    ) -> dict[str, Any]:
        """Attach (or replace) the stop-loss/take-profit bracket, or trailing
        stop, on an isolated margin position. Bracket legs and trailing
        distance are mutually exclusive families; within `trailing`, supply
        exactly one of `trail_amount`/`trail_bps`. Omitted legs are cleared —
        this call fully replaces the position's trigger of this `kind`."""
        self._guard_live_order()
        body: dict[str, Any] = {"kind": kind}
        if stop_loss_price is not None:
            body["stop_loss_price"] = stop_loss_price
        if take_profit_price is not None:
            body["take_profit_price"] = take_profit_price
        if trail_amount is not None:
            body["trail_amount"] = trail_amount
        if trail_bps is not None:
            body["trail_bps"] = trail_bps
        return self._request(
            "PUT", f"/margin/isolated/positions/{ticker}/exit_trigger", json_body=body
        )

    def cancel_isolated_exit_trigger(
        self, ticker: str, *, kind: ExitTriggerKind | None = None
    ) -> dict[str, Any]:
        """Cancel the isolated position's exit trigger(s). Omitting `kind`
        cancels both bracket and trailing triggers on this position."""
        self._guard_live_order()
        params: dict[str, Any] = {}
        if kind is not None:
            params["kind"] = kind
        return self._request(
            "DELETE", f"/margin/isolated/positions/{ticker}/exit_trigger", params=params
        )

    # -- exit triggers: cross (non-isolated) positions (tasks.md 4.5) -----------

    def get_cross_exit_triggers(
        self, ticker: str, *, subaccount: int | None = None, kind: ExitTriggerKind | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if subaccount is not None:
            params["subaccount"] = subaccount
        if kind is not None:
            params["kind"] = kind
        return self._get(f"/margin/cross/positions/{ticker}/exit_trigger", params)

    def set_cross_exit_trigger(
        self,
        ticker: str,
        *,
        kind: ExitTriggerKind = "bracket",
        count: str | None = None,
        anchor_order_id: str | None = None,
        client_trigger_id: str | None = None,
        stop_loss_price: str | None = None,
        take_profit_price: str | None = None,
        trail_amount: str | None = None,
        trail_bps: int | None = None,
    ) -> dict[str, Any]:
        """Attach a stop-loss/take-profit bracket, or trailing stop, on a
        cross-margin position. Unlike the isolated route, a cross position
        can carry multiple independent brackets: `count` covers only part of
        the position, and `anchor_order_id` ties a bracket to a specific
        entry order — both require a `client_trigger_id` to identify this
        bracket for later update/cancel. Omit both to cover the whole
        position with a single (the default) bracket."""
        self._guard_live_order()
        if (count is not None or anchor_order_id is not None) and client_trigger_id is None:
            raise ValueError(
                "client_trigger_id is required when count or anchor_order_id is set"
            )
        body: dict[str, Any] = {"kind": kind}
        if count is not None:
            body["count"] = count
        if anchor_order_id is not None:
            body["anchor_order_id"] = anchor_order_id
        if client_trigger_id is not None:
            body["client_trigger_id"] = client_trigger_id
        if stop_loss_price is not None:
            body["stop_loss_price"] = stop_loss_price
        if take_profit_price is not None:
            body["take_profit_price"] = take_profit_price
        if trail_amount is not None:
            body["trail_amount"] = trail_amount
        if trail_bps is not None:
            body["trail_bps"] = trail_bps
        return self._request(
            "PUT", f"/margin/cross/positions/{ticker}/exit_trigger", json_body=body
        )

    def update_cross_exit_trigger(
        self,
        ticker: str,
        trigger_id: str,
        *,
        stop_loss_price: str | None = None,
        take_profit_price: str | None = None,
    ) -> dict[str, Any]:
        """Update one bracket's leg prices in place, leaving any other
        brackets on the position untouched. At least one leg is required;
        omitting a leg clears it."""
        self._guard_live_order()
        if stop_loss_price is None and take_profit_price is None:
            raise ValueError("at least one of stop_loss_price/take_profit_price is required")
        body: dict[str, Any] = {}
        if stop_loss_price is not None:
            body["stop_loss_price"] = stop_loss_price
        if take_profit_price is not None:
            body["take_profit_price"] = take_profit_price
        return self._request(
            "PUT",
            f"/margin/cross/positions/{ticker}/exit_trigger/{trigger_id}",
            json_body=body,
        )

    def cancel_cross_exit_triggers(
        self, ticker: str, *, subaccount: int | None = None, kind: ExitTriggerKind | None = None
    ) -> dict[str, Any]:
        """Cancel all exit triggers (optionally filtered to one `kind`) on a
        cross position, including partial and order-anchored brackets.
        Succeeds even when nothing is live; use
        `cancel_cross_exit_trigger_by_id` to cancel a single bracket."""
        self._guard_live_order()
        params: dict[str, Any] = {}
        if subaccount is not None:
            params["subaccount"] = subaccount
        if kind is not None:
            params["kind"] = kind
        return self._request(
            "DELETE", f"/margin/cross/positions/{ticker}/exit_trigger", params=params
        )

    def cancel_cross_exit_trigger_by_id(
        self, ticker: str, trigger_id: str, *, subaccount: int | None = None
    ) -> dict[str, Any]:
        """Cancel a single bracket by ID, leaving any others on the position live."""
        self._guard_live_order()
        params: dict[str, Any] = {}
        if subaccount is not None:
            params["subaccount"] = subaccount
        return self._request(
            "DELETE",
            f"/margin/cross/positions/{ticker}/exit_trigger/{trigger_id}",
            params=params,
        )


__all__ = ["KalshiMarginClient"]
