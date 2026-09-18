# Round 4 feasibility and series-discovery report

Run date: 2026-09-06 UTC. This is a research/discovery record, not evidence
for promotion or a trading authorization.

## Kalshi public series discovery

The public Kalshi API confirmed active 15-minute binary series for BTC, ETH,
SOL, XRP, DOGE, BNB, HYPE, NEAR, and ZEC. All nine report the expected
`fifteen_min` frequency and CF Benchmarks settlement source. LINK has no event
series configured by design.

Hourly series were active for BTC, ETH, SOL, XRP, DOGE, BNB, and HYPE. The
currently configured NEAR (`KXNEARD`) and ZEC (`KXZECD`) hourly series returned
`no_active_markets`, so both are explicitly ineligible for that cadence. This
is a snapshot: it neither changes lifecycle mode nor authorizes collection or
execution beyond the registry rules.

The machine-readable evidence is in `kalshi-series-discovery-2026-09-06.json`.

## Coinbase 15-minute directional feasibility study

Dataset: 2,880 completed Coinbase BTC-USD 15-minute candles (30 days), with no
gap pairs excluded. The target was the next completed-window direction
(`close[t+1] >= close[t]`), a proxy for Kalshi's up/down event direction.

| simple rule | accuracy | 95% Wilson interval | two-sided binomial p | verdict |
| --- | ---: | ---: | ---: | --- |
| continue prior bar direction | 48.96% | 47.13%–50.78% | 0.271 | no signal |
| reverse prior bar direction | 51.04% | 49.22%–52.87% | 0.271 | no signal |

Neither interval excludes 50%, so the result is **NO GO for this bare
one-bar directional rule**. It has no demonstrated directional edge before
Kalshi spread, fees, fill uncertainty, or adverse selection; those costs would
make the required executable edge higher, not lower.

This is not a settlement-equivalent backtest. Coinbase is a proxy, while the
contracts settle on CF Benchmarks RTI averages; the study has no Kalshi quotes,
fills, BRTI readings, or realized trading costs. Any future candidate must use
the causal KXBTC15M/BRTI validation and promotion gate.

The machine-readable result is in `coinbase-15m-direction-study-2026-09-06.json`.
