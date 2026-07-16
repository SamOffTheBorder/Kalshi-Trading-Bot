# Proposal: paper-trading-and-notify

> **GATED — do not begin implementation until `core-data-and-backtesting` task 8.4
> (frozen-config validation) passes and that change is archived.** This proposal is
> drafted early so Phase 2 can start the day the gate clears. If validation fails,
> this change is re-scoped around whichever strategy family replaces crypto
> mispricing; the paper/notify infrastructure itself is strategy-agnostic and survives.

## Why

Backtesting (Change #1) validates a strategy against the past; it cannot validate the
live data path, quote freshness, evaluation timing, or our own operational readiness.
Phase 2 forward-validates in paper mode: the identical strategy/risk code driven by
live Kalshi market data, with simulated fills, for a minimum 2-4 week window. v1 had no
remote control surface at all (`winsound.Beep()` + a Windows-console-only stdin loop);
this change builds the Telegram/Discord command layer and the EmergencyControl
chokepoint before any live-money path exists, so the control surface is proven while
mistakes are still free.

## What Changes

- New `execution/paper_broker.py`: implements `BrokerAdapter` against live quotes with
  simulated fills — same fill-realism rules the backtest broker earned this week
  (pessimistic pricing, liquidity cap vs observed volume)
- New `data/kalshi/ws.py`: authenticated-optional WebSocket client (`orderbook_delta`
  with sequence tracking + snapshot resync; falls back to REST polling), feeding the
  same quote shape the strategy already consumes
- New paper trading loop in `main.py`: asyncio task wiring data → strategy → risk
  (Kelly, EntryThrottle, DrawdownGuard) → PaperBroker, persisting every Decision and
  simulated fill to the existing schema (`mode="paper"`)
- New `risk/emergency_control.py`: single `request_halt(reason, source)` /
  `resume(approved_by)` chokepoint; DrawdownGuard HALT, OS signals, and chat commands
  all converge here
- New `notify/` package: Telegram + Discord bots as asyncio tasks sharing one event
  layer — push alerts (fills, guard transitions, halt events, daily paper summary) and
  commands (`/status`, `/trades`, `/pnl`, `/pause`, `/resume`, `/panic` with
  confirmation)
- Contract tests against the Kalshi demo environment (integration-marked), plus an
  EmergencyControl test asserting all trigger sources converge on identical behavior

## Capabilities

### New Capabilities

- `paper-trading`: forward-validation of any `StrategyProtocol` strategy against live
  market data with simulated, liquidity-realistic fills
- `live-market-data`: streaming/polled Kalshi quotes with staleness detection
- `emergency-control`: one halt/resume chokepoint reachable from every surface
- `notifications`: Telegram/Discord push alerts + two-way command handling

### Modified Capabilities

- `risk-sizing`: DrawdownGuard and EntryThrottle wired into a live loop for the first
  time (paper mode) — same objects, new caller

## Impact

- New packages: `notify/`; new modules in `execution/`, `risk/`, `data/kalshi/`
- New dependencies: `python-telegram-bot`, `discord.py` (or `nextcord`), `websockets`
- New Settings usage: `telegram_*`, `discord_*` fields already exist; add staleness and
  paper-loop cadence knobs when implementation starts
- Exit gate (Phase 2 → Phase 3/4 eligibility): ≥2-4 weeks unattended paper operation,
  results directionally consistent with the frozen-config backtest, all control
  commands manually verified from both Telegram and Discord
