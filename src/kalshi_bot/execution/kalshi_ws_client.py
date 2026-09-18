"""Kalshi authenticated WebSocket client (spec: kalshi-authenticated-api, tasks.md §4.6).

Single connection, multiple channel subscriptions: `orderbook_delta` (incremental
orderbook), `ticker` (last price / mark price / volume), and the authenticated
`fill` / `user_orders` channels for this account's own activity.

Verified against `docs.kalshi.com/websockets*` 2026-09-06:

- URL: `wss://{demo-,}api.../trade-api/ws/v2` — same host family as the REST
  client, distinct path.
- Handshake auth is the *same* RSA-PSS scheme as REST (`sign_request` from
  `kalshi_client.py`, reused as-is here), signing
  `timestamp_ms + "GET" + "/trade-api/ws/v2"` and sent as the same three
  `KALSHI-ACCESS-*` headers — no separate WS credential.
- Subscribe command: `{"id": N, "cmd": "subscribe", "params": {"channels":
  [...], "market_ticker" | "market_tickers": ...}}`. `id` increments per
  command sent on this connection so responses/errors can be correlated back
  (not exercised further here — this client doesn't yet wait for per-command
  acks, see the class docstring for that scope note).
- Every data message carries `type`, `sid` (subscription id), and for
  orderbook messages a monotonically increasing `seq`. A gap in `seq` means
  dropped messages: this client detects the gap and resyncs by resubscribing
  fresh rather than trying to patch a torn book back together.
- The server pings every ~10s (control frame, not a JSON message); the
  `websockets` library answers pings automatically, so no application code
  is needed for keep-alive.

This is a read/receive client only — no order placement happens here, only
market data and the authenticated fills/orders feed. Nothing in this file
makes any live connection on import or at test time: unit tests run a fake
in-process WS server via `websockets.serve` on localhost, never Kalshi's
demo or production endpoints.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable, Iterable
from pathlib import Path
from typing import Any, Literal

import websockets
from loguru import logger

from kalshi_bot.execution.kalshi_client import load_private_key, sign_request

PROD_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
DEMO_WS_URL = "wss://demo-api.kalshi.co/trade-api/ws/v2"
_WS_SIGNING_PATH = "/trade-api/ws/v2"

Channel = Literal["orderbook_delta", "ticker", "trade", "fill", "user_orders"]


class KalshiWebSocketClient:
    """Connects, subscribes to channels, and yields decoded messages.

    Scope of this implementation (tasks.md 4.6): connection + auth headers,
    subscribe, sequence-gap detection with resubscribe-based resync, and a
    typed async-iterator interface (`messages()`). It does NOT implement
    `update_subscription`/`unsubscribe` (Kalshi's docs reference these but
    don't publish a canonical schema as of this writing — resync here always
    goes through a fresh `subscribe` on a fresh connection rather than
    guessing at an unverified in-place command), and it does not wait for or
    validate per-command subscribe acknowledgements. Both are reasonable
    additions later but aren't required for a bot that only needs to *read*
    the feed and knows how to reconnect.
    """

    def __init__(
        self,
        *,
        key_id: str,
        private_key_path: Path,
        use_demo_env: bool = True,
        ping_timeout_s: float = 15.0,
    ) -> None:
        self._key_id = key_id
        self._private_key = load_private_key(private_key_path)
        self._use_demo_env = use_demo_env
        self._url = DEMO_WS_URL if use_demo_env else PROD_WS_URL
        self._ping_timeout_s = ping_timeout_s
        self._next_cmd_id = 1
        self._last_seq_by_sid: dict[int, int] = {}

        logger.info(
            "KalshiWebSocketClient: {} environment ({})",
            "DEMO" if use_demo_env else "PRODUCTION",
            self._url,
        )

    def _auth_headers(self) -> dict[str, str]:
        timestamp_ms = str(int(time.time() * 1000))
        signature = sign_request(self._private_key, timestamp_ms, "GET", _WS_SIGNING_PATH)
        return {
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        }

    def _subscribe_command(
        self,
        channels: Iterable[Channel],
        *,
        market_ticker: str | None = None,
        market_tickers: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"channels": list(channels)}
        if market_ticker is not None:
            params["market_ticker"] = market_ticker
        if market_tickers is not None:
            params["market_tickers"] = market_tickers
        cmd = {"id": self._next_cmd_id, "cmd": "subscribe", "params": params}
        self._next_cmd_id += 1
        return cmd

    async def messages(
        self,
        channels: Iterable[Channel],
        *,
        market_ticker: str | None = None,
        market_tickers: list[str] | None = None,
        connect: Callable[..., Any] = websockets.connect,
    ) -> AsyncIterator[dict[str, Any]]:
        """Connect, subscribe, and yield decoded JSON messages forever.

        On a detected sequence gap (an orderbook_delta/orderbook_snapshot
        `seq` that doesn't immediately follow the last one seen for that
        `sid`), this logs a warning and yields a synthetic
        `{"type": "resync_required", "sid": ...}` message so callers can
        drop their local book state — it does not reconnect itself; the
        caller's consumption loop deciding whether/how to reconnect is what
        the `async for` around this generator naturally provides on
        `StopAsyncIteration` or an exception.
        """
        headers = self._auth_headers()
        async with connect(self._url, additional_headers=headers) as ws:
            subscribe_msg = self._subscribe_command(
                channels, market_ticker=market_ticker, market_tickers=market_tickers
            )
            await ws.send(json.dumps(subscribe_msg))
            async for raw in ws:
                message = json.loads(raw)
                gap_message = self._check_sequence_gap(message)
                if gap_message is not None:
                    yield gap_message
                yield message

    def _check_sequence_gap(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Track per-subscription `seq` for messages that carry one
        (orderbook snapshots/deltas). Returns a resync-required marker if a
        gap is detected, else None. Non-sequenced message types (ticker,
        fill, user_orders) pass through untouched — they're not incremental
        state that can be "torn"."""
        seq = message.get("seq")
        sid = message.get("sid")
        if seq is None or sid is None:
            return None
        last_seq = self._last_seq_by_sid.get(sid)
        self._last_seq_by_sid[sid] = seq
        if last_seq is not None and seq != last_seq + 1:
            logger.warning(
                "KalshiWebSocketClient: sequence gap on sid={} (had {}, got {}) — resync required",
                sid,
                last_seq,
                seq,
            )
            return {
                "type": "resync_required",
                "sid": sid,
                "expected_seq": last_seq + 1,
                "got_seq": seq,
            }
        return None


__all__ = ["DEMO_WS_URL", "PROD_WS_URL", "Channel", "KalshiWebSocketClient"]
