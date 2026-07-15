# Kalshi-AutoTrader v2

Multi-market trading bot, rebuilt from scratch on the lessons of v1:

- **Kalshi event contracts** (crypto, weather, economic indicators) — primary venue
- **Webull defined-risk options** on liquid underlyings — secondary venue (own risk model, own phase gate)
- **Backtest-first**: no strategy touches paper trading until it clears a fee-adjusted bar on out-of-sample history, and no strategy touches live money until it also forward-validates in paper mode
- **AI, layered**: free local Hugging Face models (FinBERT sentiment, Chronos-2 forecasting) as quantitative signal inputs; local Ollama for routine checks; OpenRouter (budget-capped) for a fail-closed pre-trade veto. AI can *propose* config changes — only a human can approve them.
- **Remotely controllable**: Telegram/Discord two-way commands + LAN web dashboard, all hitting one `EmergencyControl` chokepoint (pause / resume / panic-close)

## Why the rewrite

v1 reached ~50-51% live win rate — a coin flip that loses money after Kalshi's 7% fee — because there was no backtesting engine to validate the edge cheaply first. Its final commit didn't even parse (unresolved merge conflicts). This version is structured so those failures are impossible-by-construction: CI on every push, `.env.example` generated from the `Settings` model (drift = build failure), identical strategy code in backtest/paper/live modes, and go/no-go gates between phases.

## Quickstart

```bash
uv sync                                        # Python 3.12, pinned via .python-version
uv run pytest                                  # unit + backtest tests
uv run python scripts/generate_env_example.py  # regenerate .env.example after Settings changes
```

Copy `.env.example` to `.env` and fill in what you need. **All credentials are optional** — backtesting against public Kalshi historical data requires none.

## Project workflow

Changes are planned and tracked with [OpenSpec](https://openspec.dev/) (`openspec/`), documented with [Docusaurus](https://docusaurus.io/) (`docs-site/`). Current change sequence:

1. `core-data-and-backtesting` — Kalshi data ingestion, pricing signals, backtest engine. **No live-order code.**
2. `paper-trading-and-notify` — paper broker, live data feeds, Telegram/Discord, risk gating
3. `dashboard-and-live-gate` — web dashboard, then the live order path behind explicit go/no-go criteria

## Layout

```
src/kalshi_bot/     the bot package (config is the single source of truth: config/settings.py)
scripts/            generators & operational helpers
tests/              unit / backtest / integration (integration = sandbox APIs, off by default)
openspec/           change proposals & specs
docs-site/          Docusaurus documentation site
secrets/            gitignored; RSA keys live here, never in the repo
```
