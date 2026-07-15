"""Daily spot klines for volatility estimation.

Sources are CF Benchmarks constituent exchanges (Coinbase, Kraken) because
Kalshi settles crypto contracts against the CF Benchmarks Real-Time Index —
v1's correct design choice, preserved. Binance is deliberately absent.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

COINBASE_BASE = "https://api.exchange.coinbase.com"
KRAKEN_BASE = "https://api.kraken.com"

# Kraken pair aliases: request pair -> result key differs (XBTUSD -> XXBTZUSD).
KRAKEN_PAIRS = {"BTC-USD": "XBTUSD", "ETH-USD": "ETHUSD"}


def fetch_kraken_daily(symbol: str, *, timeout_s: float = 15.0) -> list[dict[str, Any]]:
    """~720 most recent daily candles in one request. Returns SpotCandle kwargs."""
    pair = KRAKEN_PAIRS.get(symbol)
    if pair is None:
        raise ValueError(f"unsupported symbol {symbol!r}")
    with httpx.Client(base_url=KRAKEN_BASE, timeout=timeout_s) as client:
        resp = client.get("/0/public/OHLC", params={"pair": pair, "interval": 1440})
        resp.raise_for_status()
        data = resp.json()
    if data.get("error"):
        raise RuntimeError(f"kraken error: {data['error']}")
    result = data["result"]
    rows = next(v for k, v in result.items() if k != "last")
    return [
        {
            "exchange": "kraken",
            "symbol": symbol,
            "period_minutes": 1440,
            "open_ts": int(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[6]),
        }
        for r in rows
    ]


def fetch_coinbase_daily(
    symbol: str, *, days: int = 365, timeout_s: float = 15.0
) -> list[dict[str, Any]]:
    """Up to `days` daily candles, paged at Coinbase's 300-candle limit."""
    out: list[dict[str, Any]] = []
    end = int(time.time())
    remaining = days
    with httpx.Client(base_url=COINBASE_BASE, timeout=timeout_s) as client:
        while remaining > 0:
            chunk = min(remaining, 300)
            start = end - chunk * 86400
            resp = client.get(
                f"/products/{symbol}/candles",
                params={"granularity": 86400, "start": start, "end": end},
            )
            resp.raise_for_status()
            rows = resp.json()  # [[time, low, high, open, close, volume], ...] newest first
            if not rows:
                break
            out.extend(
                {
                    "exchange": "coinbase",
                    "symbol": symbol,
                    "period_minutes": 1440,
                    "open_ts": int(r[0]),
                    "open": float(r[3]),
                    "high": float(r[2]),
                    "low": float(r[1]),
                    "close": float(r[4]),
                    "volume": float(r[5]),
                }
                for r in rows
            )
            end = start
            remaining -= chunk
            time.sleep(0.35)  # public rate limit courtesy
    return out
