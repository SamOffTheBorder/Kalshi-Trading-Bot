---
sidebar_position: 2
---

# Project scope & decisions

This page is the single source of truth for "what did we decide and why" — updated as
decisions change, so it stays authoritative rather than becoming a historical artifact.

## Markets

- **Kalshi is the primary and, for now, the only broker.** Crypto (`KXBTC`, `KXBTCD`,
  `KXETH`, `KXETHD`), weather (`KXHIGH*`/`KXLOW*` daily temperature series), and
  economic-indicator markets are all in scope for the strategy framework, backed by
  real backtesting before any of them get capital.
- **Webull (defined-risk options on liquid underlyings) is deferred indefinitely**,
  per explicit user direction (2026-07-16: *"lets not look at webull for now and just
  kalshi"*). It remains in the original architecture (see
  [Roadmap](./roadmap.md#deferred)) but nothing should be built or chased (including the
  OpenAPI application) until it's revisited.
- **Robinhood was ruled out permanently**, not deferred — it has no supported
  stock/options API, and the unofficial `robin-stocks` library carries real account-ban
  risk while bypassing Robinhood's own trade-confirmation safety.

## Why weather joined crypto as an active pipeline target

A spike of Kalshi's public series catalog (2026-07-16) found the daily-temperature family
dramatically more liquid than the crypto hourlies this project started with:

| Series | Volume/week | Strikes that ever trade |
|---|---|---|
| KXHIGHLAX | 5.5M contracts | 42/42 |
| KXHIGHNY | 1.4M contracts | 42/42 |
| Crypto hourlies (KXBTC etc.) | — | ~18% |

Every weather strike trades, versus roughly one in five crypto strikes. That, plus a
NOAA-forecastable underlying, makes it the natural pivot if crypto's validated edge (see
[Validation history](./status/validation-history.md)) doesn't hold up — so its data has
been archived in parallel since 2026-07-16, ahead of crypto in the archiver's rotation,
specifically so a pivot wouldn't start from a cold archive.

## Capital & risk (as currently configured)

- **$200 total bankroll.** The original 65/35 Kalshi/Webull split is moot while Webull
  is deferred — effectively 100% available to Kalshi strategies.
- **Quarter-Kelly position sizing** (`kelly_fraction = 0.25`), hard-capped at 5% of
  bankroll per position (`max_position_pct = 0.05`) regardless of what Kelly's formula
  would otherwise allow.
- **Drawdown guard**: pause new entries at 25% drawdown from a trailing peak, halt and
  require human reset at 40% drawdown from the *all-time* peak. These use different
  reference peaks on purpose — see
  [Architecture → Risk management](./architecture/overview.md#risk-management) for why.
- Every tunable above lives in `src/kalshi_bot/config/settings.py` — there is exactly one
  place these numbers are defined, and `.env.example` is generated from it (a build
  failure, not a runtime surprise, if it drifts).

## AI/ML layer (planned, not yet built)

Layered by cost and stakes, carried forward unchanged from the original plan:

1. **Free local models as signal inputs** — FinBERT for headline sentiment, Chronos-2 for
   zero-shot price forecasting, backtested for genuine lift before being trusted.
2. **Local Ollama** for routine, frequent, zero-marginal-cost tasks (regime
   classification from news).
3. **OpenRouter, sparse and budgeted** ($15/month) for exactly two things: a pre-trade
   veto on candidates that already passed every mathematical gate, and periodic strategy
   review. The veto **fails closed** — any API error or timeout blocks the trade, never
   silently approves.
4. **AI never auto-applies config changes.** It can only create a `ConfigProposal` that a
   human must explicitly approve or reject. This directly replaces v1's half-built
   "autonomous hourly self-tuning" loop, which is not being resurrected in any form.

## Hosting

Fully local on this machine for now ($0 hosting cost), with a LAN/phone-reachable web
dashboard planned for Phase 3. A move to a home server is anticipated later, which is why
the control surface (dashboard, Telegram/Discord, OS signals) is designed to be
supervision-agnostic from day one rather than console-session-shaped.

## Tooling

- **[OpenSpec](https://openspec.dev/)** drives the actual build workflow — proposals,
  specs, and tasks under `openspec/changes/`. This docs site explains and narrates; the
  OpenSpec changes are the working source of truth for what's implemented and what's
  gated.
- **Docusaurus** (this site) hosts human-readable docs, synced from OpenSpec and project
  history rather than duplicating either.
- **port.io** is planned for ops-visibility only (test coverage, secrets hygiene,
  days-since-key-rotation) — explicitly kept out of the trading-decision path.

## What "done" looks like for each phase

See [Roadmap](./roadmap.md) for the full phase list and gates. The short version: no
phase starts until the previous phase's gate criteria are met, and every gate is a
number or a manual verification step, not a feeling.
