# Tasks: paper-trading-and-notify

> GATED on `core-data-and-backtesting` 8.4 (frozen-config validation). Draft checklist —
> refine when the gate clears and implementation actually begins.

## 1. Live market data

- [ ] 1.1 `data/kalshi/ws.py`: WS client — `orderbook_delta` subscribe, sequence-number
      tracking, snapshot resync on gap/reconnect; REST-polling fallback path
- [ ] 1.2 Quote staleness detection (no update for N seconds → mark stale; strategy
      HOLDs on stale quotes the same way it HOLDs on degenerate ones)
- [ ] 1.3 Integration tests against the Kalshi demo environment

## 2. Paper broker

- [ ] 2.1 `execution/paper_broker.py`: `BrokerAdapter` over live quotes, simulated fills
      with pessimistic pricing + liquidity cap (port the rules BacktestBroker earned)
- [ ] 2.2 Orphan-position recovery on restart (positions reload from storage — v1's
      paper_trader.py pattern, now against the single schema of record)
- [ ] 2.3 Unit tests: fill rules, restart recovery, fee-at-settlement parity with
      BacktestBroker (same inputs → same PnL)

## 3. Emergency control

- [ ] 3.1 `risk/emergency_control.py`: `request_halt(reason, source)` / `resume(approved_by)`;
      halted flag checked every loop cycle; DrawdownGuard HALT wired in
- [ ] 3.2 OS signal handlers (cross-platform SIGINT/SIGTERM)
- [ ] 3.3 Integration test: halt triggered from every source converges on identical state

## 4. Paper trading loop

- [ ] 4.1 `main.py` asyncio loop: data → StrategyContext (incl. trend_zscore from live
      spot) → strategy → risk stack → PaperBroker; every Decision persisted `mode="paper"`
- [ ] 4.2 Settlement watcher: poll market results, settle paper positions, feed guard
- [ ] 4.3 Daily summary job (trades, win rate vs breakeven, drawdown, guard state)

## 5. Notifications & commands

- [ ] 5.1 `notify/events.py`: shared event layer (fill, guard transition, halt, summary)
- [ ] 5.2 `notify/telegram_bot.py`: push + commands (`/status`, `/trades`, `/pnl`,
      `/pause`, `/resume`, `/panic` w/ confirmation); chat-id allowlist
- [ ] 5.3 `notify/discord_bot.py`: same command set over the same event layer
- [ ] 5.4 Manual end-to-end verification from a phone (both platforms), documented in
      a runbook page

## 6. Validation window

- [ ] 6.1 Run paper mode unattended ≥2 weeks; no unhandled crashes (heartbeat check)
- [ ] 6.2 Compare paper results to the frozen-config backtest expectation; record verdict
- [ ] 6.3 Gate review: propose go/no-go for Phase 3/4 in this change's notes.md
