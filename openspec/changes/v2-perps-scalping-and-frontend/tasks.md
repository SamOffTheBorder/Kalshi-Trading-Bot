# Tasks: v2-perps-scalping-and-frontend

Ordered by dependency. §1 blocks everything — do not skip it to get to strategy work.

## 1. Archiver reliability + data expansion (BLOCKING — do this first)

**Superseded by user decision (2026-09-04): no unattended/background process,
ever.** No Windows Scheduled Task, no NSSM service, no auto-restart, no
staleness alarm — those only make sense for something meant to run without a
human watching it, which the user explicitly ruled out. Original 1.1/1.2 below
struck; see proposal.md O1 for the accepted trade-off (a missed manual
check-in can lose data once it rolls off Kalshi's ~6-week window).

- [x] 1.1 ~~Convert `start_archiver.bat` to a **Windows Scheduled Task** (or NSSM
      service)~~ **Won't do — see note above.** Data collection is manual:
      run `fetch_historical.py` (or `start_archiver.bat` for a bounded
      foreground session) by hand, periodically, at the operator's discretion.
- [x] 1.2 ~~Staleness alarm~~ **Won't do — see note above.** No unattended
      process means no silent-death failure mode to detect.
- [x] 1.1a Trim archiver to crypto-only: drop weather series (`KXHIGHNY`,
      `KXHIGHLAX`, `KXHIGHMIA`, `KXHIGHCHI`, `KXHIGHAUS`, `KXHIGHDEN`,
      `KXHIGHPHIL`, `KXLOWTOKC`, `KXLOWTDC`) from `scripts/archiver_loop.py`'s
      `SERIES` list. Keep `KXBTC`, `KXBTCD`, `KXETH`, `KXETHD` (+ `KXBTC15M`,
      added per 1.5). Existing weather rows stay in the DB for reference;
      nothing new is collected for them.
- [x] 1.3 ~~Dedicated `KXBTC15M` collector~~ **Not needed — original premise was
      wrong (O3 corrected).** Verified live 2026-09-04: `get_candlesticks` for a
      *settled* `KXBTC15M` market returns its complete 1-minute bid/ask/OI/volume
      history via the same endpoint used for `KXBTC`/`KXBTCD`. Ran
      `fetch_historical.py --series KXBTC15M --period 1` with zero code changes:
      300 candles over 20 markets, 0 gaps. `KXBTC15M` is now just another entry
      in the series list (see 1.1a/1.5) — no dedicated near-real-time collector
      required.
- [ ] 1.4 Extend archiver to perps: mark price, funding rate history, and the current
      funding estimate (`/margin` funding endpoints). **Blocked on §4, not just
      ordered after it — verified live (2026-09-04) that every `/margin` endpoint
      requires authenticated RSA-PSS-signed requests (`/margin-rest/market/*`,
      `/margin-rest/funding/*`); there is no public/unauthenticated path the way
      event-contract data has. `execution/kalshi_client.py`'s signer (§4.1) must
      exist first.** Do not build a throwaway signer here — do this once, in §4,
      correctly.
- [x] 1.5 Backfill `KXBTC15M` as far as the API allows; record honestly how far back that
      reaches (may be short — this is a newer series). **Done — result was
      better than expected.** Full run (no `--max-markets` cap): **6,444
      markets, 96,264 new candles, coverage 2026-06-28 23:46 → 2026-09-05
      00:45, only 11 gaps.** That's ~9.6 weeks — deeper than the ~6-week
      window the proposal assumed for the hourly ladders. `KXBTC15M`'s
      candlestick history did not roll off during the fetch, which took
      several minutes under Kalshi's rate limit (429s throughout, all
      auto-retried per existing backoff — never a hard failure).
- [x] 1.6 Verify coverage: a report showing per-series first/last timestamp and gap count,
      run daily and surfaced in the dashboard. ("Run daily" here means run manually,
      periodically — no scheduled/background job, per O1.) `fetch_historical.py
      --report` already produces exactly this, generically, for any series —
      zero code changes needed (see 1.3's note: this function was already
      correct). The "surfaced in the dashboard" half is blocked on §9
      (dashboard doesn't exist yet), same pattern as 1.4/perps on §4.
      **Full crypto coverage as of this session (2026-09-04):**

      | Series | First | Last | Gaps |
      |---|---|---|---|
      | `KXBTC` | 2026-05-08 20:01 | 2026-07-23 11:00 | 412 |
      | `KXBTCD` | 2026-05-08 20:01 | 2026-07-23 11:00 | 105 |
      | `KXBTC15M` | 2026-06-28 23:46 | 2026-09-05 00:45 | 11 |
      | `KXETH` | 2026-05-08 20:01 | 2026-07-23 11:00 | 1085 |
      | `KXETHD` | 2026-05-08 20:01 | 2026-07-23 11:00 | 309 |

      **This confirms the archiver-death finding from proposal.md O1 with
      real data, not just the operator's memory of it:** every series
      collected by the old `archiver_loop.py` stops dead at **2026-07-23
      11:00** — the silent-death boundary — and has a 6-week hole between
      then and today that is now permanently unrecoverable for those four
      series (Kalshi's window has already rolled past it). `KXBTC15M` has no
      such gap only because it was never collected before this session
      started fresh today; it is not evidence the archiver problem didn't
      happen, it's a different series that simply wasn't affected because it
      wasn't being watched at all. Per the O1 decision, no automated fix is
      being built for this — the mitigation is running `fetch_historical.py`
      manually, more often, going forward.

## 2. Strategy research (parallel with §1; no code changes to live path)

- [x] 2.1 Research and document short-horizon strategies with published evidence:
      order-flow imbalance, VWAP reversion, opening-range breakout, funding-rate carry,
      momentum/pullback. For each: the claimed edge, the market conditions it needs,
      and how it would be falsified on `KXBTC15M` data. Done — see
      `strategy-research.md`, with citations. Two of the five (OFI, VWAP
      reversion) are recommended against; ORB is folded into `level_break.py`
      rather than built separately (no real "session open" on a 24/7 15-min
      binary).
- [x] 2.2 **Quantify the cost floor before designing anything.** Done — see
      `cost-floor.md`. Corrected the original estimate: a 1:1 R scalp pays the
      fee/spread on **both** entry and exit legs, not once. Computed across the
      full price range (5¢–95¢) for both taker and maker: **taker-both-legs
      breakeven peaks at 52.25%** (at 50¢: 3.5¢ fee + 2¢ spread = 5.5% cost),
      **maker-both-legs breakeven peaks at 50.45%** (at 50¢: 0.9¢ fee, no
      spread = 0.9% cost). The maker-vs-taker gap (50.45% vs 52.25%) is the
      entire margin most 40–60%-win-rate strategies are trying to clear —
      execution style is not a footnote, it's most of the edge. Score every
      §2.3 candidate against both thresholds using its realistic fill style.
- [x] 2.3 Select 2–3 candidates for implementation. Record the rationale and, explicitly,
      what would make each one fail. Done — see `strategy-research.md`'s summary
      table. Selected: `trend_scalp` (momentum/pullback, best-supported by
      published crypto-specific evidence), `level_break` (breakout continuation,
      subsuming opening-range-breakout's underlying idea), `funding_carry`
      (market-neutral, priority per design.md's fallback ordering). This
      confirms — does not expand — the three strategies tasks.md §6 already
      scoped; each now has an explicit falsification test tied to the task 2.2
      cost floor.

## 3. Fix Phase 1's bugs (blocks any trustworthy backtest)

- [x] 3.1 **Fee model correction.** Done. Added `signals/fees.py` as the single
      source of truth (`entry_fee_dollars` for order-level fees,
      `entry_fee_rate_at_price` for the per-contract rate) — placed in
      `signals/` rather than `execution/` because `strategy/` code needs it
      and `strategy/` is architecturally forbidden from importing
      `execution` (an existing test enforces this; first attempt violated it
      and was caught). Updated `execution/backtest_broker.py` (fee charged at
      `place_order`, not `settle_market`; `_OpenPosition` now carries
      `entry_fee_usd`), `risk/kelly.py` (fee raises the effective cost basis,
      not a cut of the payout; `size_binary_position` now divides budget by
      effective cost price+fee, not price alone — a real sizing bug beyond
      the settlement-timing bug, since a contract's true cost was always
      price+fee, not price), `strategy/crypto_mispricing.py` (`fee_adjusted_ev`
      subtracts the fee unconditionally rather than only from the win
      branch), `backtest/metrics.py` (`breakeven_win_rate` is now `P + fee(P)`
      per design.md). All known-answer tests recomputed against the actual
      engine output (not just hand algebra) and updated:
      `test_backtest_broker.py`, `test_risk.py`, `test_strategy.py`,
      `test_engine_known_answer.py`. Full suite green (113 passed), ruff +
      pyright clean.
- [x] 3.2 **Fill-vs-intended-price bug.** Done — chose "reject the fill when it
      falls outside the band" per the spec text. Added
      `min_entry_price_cents`/`max_entry_price_cents` to `strategy/base.py`'s
      `Decision` (a strategy declares its own tolerance; the engine stays
      strategy-agnostic and doesn't need to know `CryptoMispricingConfig`).
      `crypto_mispricing.py` populates the band from
      `min_entry_probability`/`max_entry_probability` — valid because a
      Kalshi contract's price IS its market-implied win probability, on
      either side (YES price = P(yes), NO price = P(no)). The engine checks
      `result.fill_price_cents` (the actual fill) against the band after
      `place_order`, and if it falls outside, calls the broker's new
      `void_fill()` (refunds stake+fee, drops the position — replay fills
      are immediate, so there's no resting order to cancel instead) rather
      than recording a `SimulatedTrade`. Rejection count surfaced in the
      run-complete log line. New known-answer test
      (`test_fill_outside_entry_band_is_rejected`) proves a fill that lands
      outside a declared band is voided with zero cash spent. Full suite
      green (114 passed), ruff + pyright clean.
- [x] 3.3 **Liveness filter (mandatory).** Done. Added
      `backtest/liveness.py`'s `is_live_quote(candle)`: a market is live iff
      `open_interest > 0` and both `yes_bid_close`/`yes_ask_close` are
      present and within 1-99¢ (a 0¢/100¢ "quote" is degenerate, not a real
      two-sided market). Wired into the engine right before entry
      generation — a dead-quote market still gets evaluated and its decision
      recorded (audit trail intact), but no order is ever placed for it.
      Rejection count surfaced in the run-complete log line
      (`dead_quotes`). New tests: `test_liveness.py` (6 unit cases: live,
      zero-OI, missing bid, missing ask, the exact 0¢/1¢-shell-with-zero-OI
      shape from the 92/100 sample, degenerate 100¢/100¢) and an engine
      integration test (`test_dead_quote_market_never_generates_an_entry`)
      proving a market the strategy would otherwise BUY never fills when its
      OI is zero. Full suite green (121 passed), ruff + pyright clean.
- [x] 3.4 Maker/taker modeling: the broker must distinguish resting limit fills from
      crossing fills, since it is a ~4x fee difference. Done. Added
      `OrderRequest.execution_style` ("taker" default, "maker"). Taker
      unchanged (pessimistic crossing fill, taker fee). Maker requires
      `limit_price_cents`, fills AT that exact price (never worse — that's
      the point of resting) only if the bar's OTHER side of the book traded
      through it — proof a real counterparty existed to cross the resting
      order, not an assumption that posting an order gets it picked off for
      free. YES buy resting at L: needs `yes_ask_low <= L` in the bar; NO
      buy resting at L: needs `yes_bid_high >= 100-L`. Extended `MarketBar`
      with `yes_bid_high`/`yes_ask_low` (already existed on `Candle`, just
      wasn't plumbed through) and wired the engine to pass them. Maker fee
      uses `MAKER_FEE_COEFFICIENT` (0.0175) from `signals/fees.py`; an
      untouched resting order is rejected (`resting_order_not_touched`), not
      partially filled or repriced. 6 new known-answer tests, including one
      proving the same fill price costs ~4x less as maker vs taker. Full
      suite green (126 passed), ruff + pyright clean.
- [x] 3.5 Regression-run Phase 1's run #8 config on the corrected engine and record how
      much of its result survives. Expectation: most of it does not.
      **Done — expectation confirmed, more starkly than expected.**

      Ran `scripts/run_backtest.py --split-date 2026-07-16` (run #8's exact
      frozen config: trend z 1.5/24h, throttle 3/24h, liquidity cap 25%, all
      Settings defaults) on the corrected engine (fees, fill-band gate,
      liveness filter, all from 3.1-3.3). **Caveat before the numbers: this
      is not apples-to-apples with run #8** — the archive has grown since
      then (2026-05-08 → 2026-09-05 now vs. run #8's narrower window), so
      this is "run #8's config on today's much larger archive," not a
      controlled replay of the identical dataset. Both runs are reported
      side by side for that reason.

      | | Run #8 (original, wrong fee model, larger window) | Run #9 (corrected engine, same config, full archive) |
      |---|---|---|
      | Evaluations | 990,185 | 2,834,541 |
      | Entries | 180 | 706 (+709 rejected outside entry band, +695 dead-quote markets skipped) |
      | Test trades | 64 | 82 |
      | Test win rate | 60.9% | 61.0% |
      | Test margin over breakeven | +10.2% | +7.3% |
      | Test net PnL | +$173.47 | +$1,507.31 |
      | Test Sharpe | 0.72 | **0.35** |
      | **Test top-10 trade concentration** | **122%** | **186%** |
      | **Test top-1 trade concentration** | not reported | **52.4%** |
      | Final equity ($200 start) | $419.98 | **$9,688.77** |

      **Verdict: fails the task 8.4 gate criteria decisively, on multiple
      independent grounds, not just marginally:**
      - Sharpe 0.35 is well under the 1.0 bar (run #8 was already failing
        this at 0.72; the fill-band/liveness corrections made it worse, not
        better — removing phantom fills removed some of the false edge).
      - Top-10 concentration is 186% of test profit — WORSE than run #8's
        122% finding that the original proposal cited as disqualifying, not
        an improvement.
      - **A single trade (1,372 contracts, one settlement) is 52.4% of the
        entire test-segment profit** — nowhere close to the 10% gate.
      - Position sizes (1,372 and 1,631 contracts on a $200 starting
        bankroll) are exactly Phase 1's diagnosed failure mode: Kelly
        compounding equity growth into ever-larger positions in markets that
        cannot actually support that size. The $9,688.77 final equity (48x
        starting capital) is not a validated edge, it is Kelly compounding
        on a strategy this project has already retired.

      **This does not contradict D3's decision to remove Kelly from the live
      path — it reconfirms exactly why that decision was made**, using fresh
      evidence from the corrected engine rather than repeating the original
      finding. `crypto_mispricing` remains parked, per proposal.md's Removed
      Capabilities. No further tuning of this config is planned; the
      corrected engine itself (fees, fill-band, liveness) is what's carried
      forward into `scalping-strategies`' backtests (task 8), not this
      strategy or its Kelly sizing.

## 4. Authenticated Kalshi client

- [x] 4.1 `execution/kalshi_client.py`: RSA-PSS request signing (key at
      `secrets/kalshi_private_key.pem`, already validated 2048-bit; key ID in
      `KALSHI_KEY_ID`). Signs `timestamp_ms + method + path` (RSA-PSS,
      MGF1/SHA256, salt length = digest length) via `sign_request()`; base URL
      selected by `Settings.kalshi_use_demo_env`, never a constructor default.
      **Note — base URLs corrected from this task's original text during
      implementation**, matching the working public client rather than the
      literal `external-api.*` hosts written above: prod
      `https://api.elections.kalshi.com/trade-api/v2` (validated live, see
      4.2), demo `https://demo-api.kalshi.co/trade-api/v2` (**unvalidated —
      no demo call has been made**; verify before relying on it). 9 unit
      tests (`tests/unit/test_kalshi_client.py`) cover signature
      verifiability (round-tripped through the public key), signature
      uniqueness per path, demo/prod URL selection, and auth headers on
      outgoing requests, using the same `httpx.MockTransport` pattern as
      `data/kalshi/client.py`'s tests.
- [x] 4.2 **Read-only endpoints first** — balance, positions, fills, orders
      (`get_balance`/`get_positions`/`get_fills`/`get_orders`), same
      fail-fast-401/backoff-on-429-or-5xx retry pattern as the public client.
      **Smoke-tested live against production** (2026-09-06, explicit user
      decision to test against prod as configured rather than demo — see
      proposal/session notes) with the real `.env` credentials: all four
      endpoints returned real account data — balance $57.7318, zero open
      positions, real recent fills and orders on `KXBTC15M`/`KXBTCD`
      tickers (maker and taker fills both present, fees consistent with
      the corrected fee model from §3.1). This is real, pre-existing
      account activity, not anything this session initiated — confirms the
      signing scheme and endpoint wiring are correct end-to-end, and
      finally makes the user's real trading history visible to the bot, as
      this task originally intended (demo smoke test still outstanding).
      Order placement remains out of scope until 4.3 is explicitly
      authorized.
- [x] 4.3 Event-contract order placement implementing `BrokerAdapter`: limit orders
      (maker-preferred), cancel, amend. **Code + unit tests only — deliberately
      not smoke-tested against demo or production** (explicit user decision
      2026-09-06: build and test against mocked HTTP first, live demo
      validation is a separate, later, explicit step). Added
      `create_order`/`cancel_order`/`amend_order` to
      `execution/kalshi_client.py` (POST/DELETE variant of the existing
      GET-only `_get` retry/backoff pattern, via new `_request()`); a fresh
      UUID `client_order_id` per call unless the caller supplies one, so a
      caller's own retry can't silently double-submit. Added
      `execution/kalshi_broker.py`'s `KalshiBroker`, implementing the async
      `BrokerAdapter` protocol by wrapping the synchronous client's calls in
      `asyncio.to_thread` (no second HTTP stack needed). Maps Kalshi's
      three-state order lifecycle (`resting`/`executed`/other) onto
      `BrokerAdapter`'s two-state `OrderResult` conservatively: an unfilled
      resting limit order reports `status="rejected"`,
      `reject_reason="resting_unfilled"` rather than a false "filled" —
      `OrderResult` has no partial/resting state of its own, and claiming a
      fill that didn't happen is worse than under-reporting. `get_market_snapshot`
      intentionally raises `NotImplementedError`: the authenticated client
      only covers `/portfolio`, not market data — a real snapshot belongs to
      `data/kalshi/client.py`'s public client, not duplicated here. 16 new
      unit tests (7 in `test_kalshi_client.py`, 7 in `test_kalshi_broker.py`,
      all `httpx.MockTransport`-mocked), full suite green (149 passed), ruff
      + pyright clean. **Spec gap found and fixed during 4.4's work:** the
      kalshi-authenticated-api spec's "Demo and production environments are
      structurally distinct" requirement ("SHALL refuse to place orders
      against production while `paper_trading` is true") was not actually
      enforced — `create_order`/`amend_order` had no `paper_trading`
      awareness at all. Added a `paper_trading: bool = True` constructor
      param and `_guard_live_order()`, called before any network request in
      both methods; raises the new `KalshiConfigError` if
      `use_demo_env=False` and `paper_trading=True`. 5 new tests cover the
      block, the demo-always-allowed case, and the explicit
      `paper_trading=False` escape hatch.
- [x] 4.4 `/margin` (perps) client: markets, orderbook, positions, risk (leverage +
      liquidation price), funding history/estimate, order placement. **Code +
      unit tests only — no live call made against demo or production**, same
      discipline as 4.3. Added `execution/kalshi_margin_client.py`'s
      `KalshiMarginClient` — a sibling to `KalshiAuthenticatedClient`, not a
      subclass, since perps and event contracts never share a call site;
      duplicates the same signing/retry/throttle transport rather than
      inheriting it, kept deliberately simple over a shared-base
      refactor. **Path correction found during this task:** tasks.md 1.4
      and this file's own earlier draft assumed a separate `/margin-rest/*`
      host per `docs.kalshi.com`'s documentation-page URLs — verified live
      against the docs (2026-09-06) that these are actually just
      `docs.kalshi.com` *doc-page* paths, not real API routes. The real API
      paths ride under the same `/trade-api/v2/margin/*` prefix as
      everything else (e.g. `GET {base}/trade-api/v2/margin/positions`),
      confirmed against `docs.kalshi.com/margin-rest/portfolio/get-positions.md`
      and siblings for every endpoint implemented. Covers `get_markets`,
      `get_market`, `get_market_orderbook`, `get_positions`, `get_balance`,
      `get_risk`, `get_risk_parameters`, `get_notional_risk_limit`,
      `get_funding_rate_estimate`, `get_historical_funding_rates`, and
      `create_order` (margin order fields — `count`/`price` as fixed-point
      dollar/contract strings per Kalshi's own docs, not floats, to avoid
      wire-precision drift). `create_order` defaults `post_only=True` (spec:
      "Maker-preferred order placement") and carries the identical
      prod+paper_trading guard as 4.3's fix, including its own
      `KalshiConfigError`. 12 new unit tests, all `httpx.MockTransport`-mocked.
      Full suite green (165 passed), ruff + pyright clean. Exit-trigger
      endpoints (isolated/cross stop-loss/take-profit, trailing stops) are
      explicitly out of scope here — that's 4.5.
- [x] 4.5 **Exit-trigger API**: attach stop-loss/take-profit brackets and trailing stops.
      This is the auto-stop-loss requirement — server-side, so a crashed bot cannot
      orphan a leveraged position. Implemented on `KalshiMarginClient` (code + mocked-HTTP
      tests only, no live call — same discipline as 4.3/4.4). Endpoint shapes verified
      live against `docs.kalshi.com/margin-rest/exit-triggers/*` before coding rather than
      assumed. Two position types have distinct routes: **isolated**
      (`PUT`/`GET`/`DELETE /margin/isolated/positions/{ticker}/exit_trigger`) always
      covers the whole position and is fully replaced by each `set_*` call; **cross**
      (`.../margin/cross/positions/{ticker}/exit_trigger[/{trigger_id}]`) supports multiple
      independent brackets per position via `client_trigger_id` (required whenever `count`
      — a partial-size bracket — or `anchor_order_id` — tied to a specific entry order — is
      given), plus `update_cross_exit_trigger` to reprice one bracket's legs in place and
      `cancel_cross_exit_trigger_by_id` to cancel just one. Both position types support
      `kind="bracket"` (`stop_loss_price`/`take_profit_price`, either or both) and
      `kind="trailing"` (exactly one of `trail_amount`/`trail_bps`). All mutating calls
      (`set_*`/`update_*`/`cancel_*`) go through the same `_guard_live_order()`
      prod+paper_trading interlock as `create_order`. 17 new unit tests. Full suite green
      (179 passed), ruff + pyright clean.
- [x] 4.6 WebSocket client: orderbook, ticker (mark price), authenticated fills/orders,
      with sequence tracking and snapshot resync. Implemented as `KalshiWebSocketClient`
      (new `execution/kalshi_ws_client.py`), a thin sibling to the REST clients: same
      RSA-PSS signing (`sign_request`, reused as-is), signing
      `timestamp_ms + "GET" + "/trade-api/ws/v2"` and sent as the identical three
      `KALSHI-ACCESS-*` headers on the WS handshake — verified against
      `docs.kalshi.com/websockets*` and `getting_started/quick_start_websockets` 2026-09-06
      (the per-channel doc pages disagreed with each other on the subscribe shape; the
      quick-start guide's worked Python example was treated as authoritative:
      `{"id": N, "cmd": "subscribe", "params": {"channels": [...], "market_ticker" |
      "market_tickers": ...}}`). `messages()` is a single async generator: connect,
      subscribe once, yield every decoded message forever. Sequence tracking is per-`sid`
      (each channel subscription gets its own monotonic `seq` on orderbook messages only —
      ticker/fill/user_orders aren't incremental state and pass through untouched); a gap
      yields a synthetic `resync_required` marker rather than trying to patch a torn book,
      leaving the actual reconnect-and-resubscribe to the caller's consumption loop.
      Server-side ping/pong keep-alive needs no application code — `websockets` answers
      pings automatically. Added the `websockets` runtime dependency (`uv add websockets`).
      Deliberately out of scope: `update_subscription`/`unsubscribe` commands (Kalshi's own
      docs reference them but don't publish a canonical schema anywhere fetched) and waiting
      on/validating per-command subscribe acknowledgements — resync always goes through a
      fresh `subscribe` on a fresh connection instead. 7 new unit tests, run against a real
      in-process `websockets.serve` fake server on localhost — no connection made to
      Kalshi's demo or production WebSocket endpoints. Full suite green (186 passed), ruff +
      pyright clean.
- [x] 4.7 Rate-limit handling and a demo/prod guard that makes it structurally hard to
      point at production by accident. Rate-limit handling (throttle + exponential backoff
      on 429/5xx, fail-fast on 401/403) is done, same as the public client. The demo/prod
      guard: environment selection is explicit via `Settings.kalshi_use_demo_env` and
      logged loudly at client init; order placement/amend/exit-trigger writes refuse to run
      against production while `paper_trading=True` (`KalshiConfigError`, raised before any
      network request — the 4.3/4.4 spec-gap fix). Closed the remaining gap this task: a
      **live-trading confirmation flow** for the `paper_trading=False` escape hatch itself,
      closing the promise already made in `Settings.paper_trading`'s own description
      ("gated behind the live-trading confirmation flow; never edit casually"). Scoped as a
      standalone primitive rather than a dashboard/EmergencyControl UI, since neither exists
      yet (EmergencyControl is explicitly a "later change" per `risk/drawdown_guard.py`):
      new `Settings.live_trading_confirmation_phrase` (`SecretStr | None`, default `None`)
      must equal the literal, case-sensitive phrase `LIVE_TRADING_CONFIRMATION_PHRASE`
      ("I understand this places real orders", defined once in `kalshi_client.py` and
      imported by `kalshi_margin_client.py` so the two can't drift). `_guard_live_order()`
      on both `KalshiAuthenticatedClient` and `KalshiMarginClient` now checks this whenever
      `paper_trading=False` on production — `paper_trading=False` alone is no longer
      sufficient, it must be paired with typing the exact phrase into config. This is a
      deliberate typing exercise, not a UI toggle or interactive prompt: live trading can
      never turn on by flipping one boolean or by a script auto-answering a y/N prompt.
      Regenerated `.env.example` for the new field (`scripts/generate_env_example.py`); its
      diff also picked up unrelated pre-existing drift (stale `WEBULL_*`/
      `BANKROLL_SPLIT_KALSHI_PCT` lines for fields no longer in `Settings`), now cleaned up
      as a side effect. 8 new unit tests (phrase missing/wrong/correct, across both order
      placement and exit-trigger writes). Full suite green (191 passed), ruff + pyright
      clean. Still explicitly not built: any *interactive* confirmation (dashboard button,
      CLI prompt) — that belongs with the dashboard/EmergencyControl work in later sections,
      not here, per the scoping decision for this task.

## 5. Risk layer

- [x] 5.1 `risk/fixed_risk.py`: `R`-based sizing — contracts = (equity × risk_pct) / R,
      with risk_pct 1–2% and a hard cap. Replaces Kelly on the live path. `compute_r()`
      + `size_fixed_risk()`: R is the dollar distance from entry to stop; sizing clamps
      the R-based unit count against an independent notional cap (`max_position_pct`),
      same min()-clamp shape as `kelly.size_binary_position` so a degenerate (very tight)
      stop can never alone justify an oversized position. New `Settings.risk_pct` (default
      0.01, bounded to the documented 1-2% band). Fails safe (returns 0, never raises) on
      non-positive equity or a degenerate stop; raises only on genuinely invalid config
      (risk_pct/max_position_pct out of band). 9 new unit tests.
- [x] 5.2 `risk/exit_triggers.py`: bracket construction and the invariant that **no perps
      position exists without a server-side bracket**; if attaching fails, close the position.
      `attach_mandatory_bracket()` calls `KalshiMarginClient.set_isolated_exit_trigger` /
      `set_cross_exit_trigger` (4.5) and, on ANY failure, immediately submits a reduce-only,
      immediate-or-cancel closing order — the one place in the codebase where paying the
      taker fee and crossing the spread is correct, since an unbracketed leveraged position
      is worse than a fee. Returns a `BracketResult` the caller must respect: `ok=False`
      always means the position is already closed (or, in the double-failure case,
      `closed_due_to_failure=False` with a `logger.critical` — manual intervention
      required; there is nothing left to fall back to programmatically). Caller supplies
      the marketable close price rather than a hardcoded constant, since perps prices are
      real unbounded dollar amounts, not [0,1]-style event-contract pricing. 6 new unit
      tests against mocked HTTP (no live call).
- [x] 5.3 Leverage governor: cap at 2x (hard ceiling 3x), continuously monitor distance
      to liquidation, refuse entries whose stop sits inside the liquidation buffer.
      `risk/leverage_governor.py`: `check_leverage_ceiling()` (implied leverage =
      notional/equity, clamped so a misconfigured cap can never exceed
      `HARD_LEVERAGE_CEILING=3.0` in code, not just by config bounds) and
      `check_liquidation_buffer()` (rejects a stop that sits at or beyond the liquidation
      price for the position's side). Field names (`account_leverage`,
      `position_leverage`, `estimated_liquidation_price`, `mark_price`) verified against
      `docs.kalshi.com/margin-rest/risk/get-risk.md` 2026-09-06 rather than guessed;
      `find_position_risk()`/`liquidation_price_from_risk()` parse that real response
      shape directly. New `Settings.max_leverage` (default 2.0, bounded ≤3.0). 17 new
      unit tests.
- [x] 5.4 Daily loss limit + consecutive-loss halt, wired into the existing
      `DrawdownGuard` / `EmergencyControl` design from Phase 1. New `risk/daily_loss_guard.py`:
      `DailyLossGuard` (halts for the rest of the UTC calendar day once realized PnL since
      midnight breaches `-max_daily_loss_usd`; rolls over automatically at UTC midnight) and
      `ConsecutiveLossGuard` (halts after N losses in a row; any win resets the streak) —
      both distinct failure modes from `DrawdownGuard`'s equity-curve PAUSE/HALT. New
      `risk/emergency_control.py`: `EmergencyControl` is the class `DrawdownGuard`'s own
      docstring and tasks.md 9.4 both said didn't exist yet — it composes all three guards
      (`allows_new_entries()` is a straight AND) and wires any automatic trip to the
      dashboard's `web.control_state.ControlPanel.kill()` via a structural `Protocol`
      (`risk/` does not import `web/`), so the kill-switch banner and the risk layer's own
      decision are the same truth, not a second copy of it. `resume()` clears every guard
      and re-arms the panel in one explicit, human-only call — never automatic. New
      `Settings.max_daily_loss_usd` (default $20) and `max_consecutive_losses` (default 5).
      22 new unit tests (12 for the two new guards, 10 for `EmergencyControl` including its
      `ControlPanel` wiring).
- [x] 5.5 Funding-aware position management: know the next funding timestamp, the current
      estimate, and whether the position pays or receives. New `risk/funding_awareness.py`:
      `funding_state_from_estimate()` parses `KalshiMarginClient.get_funding_rate_estimate()`'s
      real response shape (`market_ticker`, `computed_time`, `funding_rate`, `mark_price`,
      `next_funding_time`, verified against `docs.kalshi.com/margin-rest/funding/
      get-funding-rate-estimate.md`). **Caveat, called out prominently in the module
      docstring and here:** Kalshi's docs describe what `funding_rate` measures but do NOT
      publish the sign convention (which side pays when it's positive) or the exact payment
      formula. This implementation assumes the convention essentially every other perp
      venue uses — positive rate means longs pay shorts, payment = notional × rate — since
      nothing in Kalshi's docs contradicts it, but this is a documented ASSUMPTION, not a
      verified fact. `pays_or_receives` (the direction) is higher-confidence than
      `estimated_payment_usd` (the exact magnitude); treat the magnitude as unverified until
      checked against a real observed payment via `get_funding_history` (4.4). 6 new unit
      tests covering all four sign/side combinations plus the zero-rate case.

      **§5 checkpoint:** full suite green (251 passed, up from 223 before §5), ruff +
      pyright clean across the whole repo after each sub-task. `.env.example` regenerated
      after every new `Settings` field (5.1, 5.3, 5.4). No live/demo network call made
      anywhere in §5 — every test uses mocked HTTP or pure in-memory state. No git commit
      made.

## 6. Strategies

- [x] 6.1 `strategy/trend_scalp.py` — deterministic level detection (swing highs/lows with
      N confirming touches, session VWAP), entry on pullback-and-hold, fixed R target.
      **Scope decision made explicitly before coding:** decision-level only — produces
      `Decision.stop_price`/`target_price` (new fields, underlying-spot terms) but does
      NOT extend `BacktestEngine` to simulate intrabar stop/target management, since that
      engine is built for `crypto_mispricing`'s single-shot settle-at-expiry model, a
      materially different execution shape; wiring fixed-R exits into the engine is
      separate, larger work, flagged for later rather than attempted here. New shared
      `strategy/levels.py` implements design D2's level definition verbatim (swing
      highs/lows over a lookback window, confirmed by N touches within a tolerance band,
      VWAP, "respected" = approached within band and closed without breaking through) —
      both `trend_scalp` and `level_break` (6.2) consume the same module rather than each
      re-deriving levels. `StrategyContext` gained `spot_bars: tuple[SpotBar, ...]` (new
      `SpotBar` OHLCV type, deliberately decoupled from the `SpotCandle` ORM row) since
      level detection needs bar history the old single-spot-value context didn't carry.
      12 known-answer tests for `levels.py`, 9 for `trend_scalp.py`.
- [x] 6.2 `strategy/level_break.py` — breakout continuation with volume confirmation.
      Buys the break of a level `levels.py` says has NOT held, gated on the breakout bar's
      volume exceeding a configurable multiple of its recent average — the confirmation
      that separates a genuine breakout from a low-conviction wick. Subsumes
      opening-range-breakout per 2.3/strategy-research.md (no real "session open" on a
      24/7 15-minute binary). Same decision-level-only scope as 6.1. 7 known-answer tests.
- [x] 6.3 `strategy/funding_carry.py` — perps/event-contract hedged funding capture.
      Market-neutral; likely the best risk-adjusted fit for a small account. Does NOT fit
      `StrategyProtocol` (single-instrument, single-decision) — this is inherently a
      two-leg, two-instrument trade, so it has its own `evaluate_funding_carry()` /
      `FundingCarryDecision` rather than forcing a two-leg trade into one `Decision`.
      Reuses `risk/funding_awareness.py`'s `FundingState` (5.5) for the funding input and
      `signals/fees.py` for the hedge leg's cost. **Real finding from building this:** the
      hedge leg's fee drag is substantial — `entry_fee_rate_at_price` peaks at a 50c
      contract, exactly where design.md recommends hedging for the most linear
      BRTI-tracking delta, so a $10k notional hedged at 50c needs ~20,000 contracts and
      ~$350 of fee drag alone, requiring a >3.5% funding rate just to break even on that
      leg. This is precisely the falsification strategy-research.md §4 anticipated;
      documented prominently in the module docstring rather than only discovered later in
      backtest. 8 known-answer tests covering both directions, the rate-floor gate, the
      net-carry gate, and hedge-cost scaling.
- [x] 6.4 Whichever additional candidates §2.3 selected. No-op: 2.3's own text confirms
      exactly 3 candidates were selected and they are precisely `trend_scalp`/
      `level_break`/`funding_carry` (6.1-6.3) — nothing additional to build.
- [x] 6.5 Known-answer unit tests for every strategy: synthetic bars → exact expected
      decisions. Same discipline as Phase 1, which is the part of Phase 1 that worked.
      36 new tests across `levels.py`/`trend_scalp.py`/`level_break.py`/`funding_carry.py`
      (counted individually in 6.1-6.3 above). Full suite green (287 passed, up from 251
      before §6), ruff + pyright clean across the whole repo. No live/demo network call
      made anywhere in §6 — pure synthetic-data unit tests throughout. No git commit made.

## 7. AI layer

- [x] 7.1 `ai/local_review.py` — Ollama client. Recommended: `qwen3:14b-q4_K_M` or
      `phi-4:14b-q4_K_M` (fit 12GB VRAM on the RTX 5070). Structured JSON in/out,
      low temperature, **fail-closed**: no or malformed response ⇒ no trade.
      `LocalReviewClient.review()` posts to Ollama's `/api/chat` with `format: "json"` and
      low temperature (0.1 default); `TradeCandidate` is a narrow, fixed input shape (not
      an open dump of every strategy variable) and `VetoVerdict` the fixed output shape.
      Fail-closed covers every failure mode with its own reason string, not just a generic
      catch-all: network/HTTP error (`request_failed:...`), empty response body
      (`empty_response`), invalid JSON (`malformed_json`), wrong top-level shape
      (`unexpected_shape`), non-boolean `approved` (`non_boolean_approved`) — every path
      returns `approved=False`, never raises. This machine already has Ollama running
      locally with a qwen3-14b-class model pulled (`huihui_ai/qwen3-abliterated:14b-q4_K_M`)
      — **live-verified**: `tests/integration/test_local_review_live.py` (run explicitly,
      `pytest -m integration`) round-tripped a real request against that model
      successfully (15.4s), confirming the wire format actually works end-to-end, not just
      against mocks. 13 mocked unit tests cover every fail-closed path plus the
      well-formed approve/reject cases.
- [ ] 7.2 `ai/forecast.py` — Chronos-Bolt short-horizon BTC forecast as a numeric signal.
      Purpose-built time-series model, not an LLM doing arithmetic. **Deferred** — needs
      new heavy dependencies (`torch`, `chronos-forecasting`) not yet added; explicit
      decision to scope this session to 7.1/7.6 only and revisit 7.2-7.5 as a separate,
      deliberate step.
- [ ] 7.3 `ai/sentiment.py` — FinBERT headline sentiment (small, CPU-fine). **Deferred** —
      needs `transformers`/`torch`, not yet installed; same deferral as 7.2.
- [ ] 7.4 `ai/openrouter.py` — slow path only: news retrieval, daily strategy review,
      weekly post-mortem. Free tier (1000/day) is sufficient; budget guard retained.
      **Deferred** — needs a real OpenRouter API key/account decision, not made this
      session.
- [ ] 7.5 Benchmark the local models on the actual veto prompt: latency, VRAM, and
      whether their verdicts correlate with realized outcomes at all. **If the veto adds
      no measurable value, remove it** rather than keeping it for reassurance. **Deferred**
      — needs real trade history to correlate against, which doesn't exist yet (no paper/
      live trading has run); the live smoke test's 15.4s single-call latency is a data
      point but not a benchmark.
- [x] 7.6 Persist every AI verdict with its trade, so §7.5 can be answered with data later.
      New `storage.models.VetoVerdictRecord` (FK to `SignalRecord`, nullable so a
      standalone benchmark run can persist without a linked signal): model name, approved,
      confidence, reason, full raw response, latency — recorded for EVERY outcome
      including every fail-closed path, not just approvals, so a systematic failure
      pattern (e.g. consistent timeouts) is visible in the data rather than silently
      absent. `ai.local_review.to_veto_verdict_record()` builds the row from a
      `VetoVerdict`. 4 new tests (2 storage roundtrip, 2 for the mapping helper), plus
      `latency_ms` now measured and threaded through every `VetoVerdict` return path in
      7.1 specifically to feed this.

      **§7 checkpoint:** full suite green (306 passed, up from 287 before §7 — includes
      the 1 live-Ollama integration test, excluded from the default `-m 'not integration'`
      run), ruff + pyright clean across the whole repo. No new dependencies added (Ollama
      talked to via the existing `httpx`). No git commit made.

## 8. Backtest + gate review (the decision point)

- [x] 8.1 Backtest each strategy on accumulated `KXBTC15M` data with corrected fees,
      liveness filtering, maker/taker distinction, and fixed-risk sizing.

      **§6's strategies were decision-level only — this task's real content turned out to
      be building the backtest engine's missing execution path, not just running it.**
      Three previously-invisible bugs found and fixed as prerequisites, each of which
      would have silently blocked or corrupted ANY real 8.1 run, not just this one:
      1. `BacktestEngine.SERIES_SYMBOL` never mapped `KXBTC15M` to a spot symbol at all —
         `KXBTC15M`, design D1's entire primary instrument, could never be backtested
         through this engine before this fix, for any strategy including `crypto_mispricing`.
      2. `StrategyContext.spot_bars` was never populated by the engine — always empty
         regardless of what spot data existed, silently making `trend_scalp`/`level_break`
         untestable (`insufficient_bar_history` on every evaluation). Fixed via a new
         `_load_spot_bars`/`_bars_before` pair, same look-ahead discipline as the rest of
         context assembly, with a new `spot_bar_window` constructor param (default 48h).
      3. No mechanism existed for intrabar stop/target exits at all — every position held
         to settlement regardless of a strategy's declared stop/target. Added
         `BacktestBroker.close_position_early()` + engine-side per-bar exit checking
         (`_fixed_r_exit_price`), gated on new `Decision.stop_price_cents`/
         `target_price_cents` fields (new `strategy.levels.spot_r_to_contract_cents()`
         converts the strategy's own spot-terms stop/target into contract-cents — NOT a
         Black-Scholes inversion, deliberately, since `KXBTC15M` is a single-strike binary
         and inverting a pricing model just to build an exit trigger would reintroduce the
         zero-drift assumption design D2 moved away from). Ambiguous bars (both stop AND
         target touched in one candle) assume the WORSE outcome, same pessimism discipline
         `BacktestBroker`'s entry fill model already applies. 9 new engine-level tests
         (4 fixed-R exit scenarios, 1 spot_bars population, 1 SERIES_SYMBOL/flush interaction).

      **A fourth, purely operational bug found while actually running this**: a multi-day
      backtest at a fine `eval_stride_s` produces millions of HOLD `SignalRecord` rows;
      never flushing the session until the final commit made every subsequent autoflush
      check progressively slower over a run's lifetime (observed directly: a 636k-evaluation
      run visibly decelerating from ~1s CPU/s to under 0.1s CPU/s over its ~3-minute
      lifetime). Fixed with a new `signal_flush_interval` param (periodic `session.flush()`,
      deliberately NOT `expire_all()` — that would risk corrupting in-flight
      `SimulatedTrade` mutations applied later in the same loop without a re-fetch;
      verified safe with a dedicated test forcing multiple mid-run flushes around a
      trade's full lifecycle). Also found: three earlier exploratory runs left ~7.9M
      stale rows (2.93GB) in the shared `data/kalshi_bot.db` from crashed/killed attempts —
      cleaned up (deleted + vacuumed); the archived market/candle/spot data itself was
      never at risk, only disposable per-run audit-trail rows were removed.

      **Real backtest results** (full 68-day accumulated window, `eval_stride_s=900`,
      $1000 starting cash, default strategy configs, 75/25 train/test split — NOT yet
      walk-forward-validated, see 8.3):
      - `trend_scalp`: **1 entry across 636,008 evaluations.** `min_trend_zscore=0.5` /
        `min_touches=2` / `level_tolerance_pct=0.003` are drastically too conservative for
        real `KXBTC15M`-adjacent conditions — this is a config-tuning finding, not a
        falsification of the underlying idea; nowhere near the ≥200-trade sample 8.4's
        gate will require.
      - `level_break`: **15 entries** (across the whole `SERIES_SYMBOL`-mapped universe —
        `KXBTCD`/`KXETHD`/`KXBTC`/`KXETH`/`KXBTC15M`, not `KXBTC15M` alone, since the
        engine backtests every mapped series in one pass), **all in the train segment,
        zero in test.** Win rate 93.3% but BELOW the 95.6% fee-adjusted breakeven (margin
        −2.3%) — yet net PnL is +$303.22. The reconciliation: `net_pnl_at_flat_sizing_usd`
        is **−$0.45** — at flat, non-compounding sizing this strategy LOSES money; the
        reported profit is a pure Kelly-compounding sizing artifact, exactly Phase 1's
        run #8 failure mode, now caught automatically by the 8.2 metric built for this.
        `top10_concentration_pct=99%` and a genuine 41.2% max drawdown (which tripped
        `DrawdownGuard`'s HALT mid-run) confirm it. Verified by hand against the raw
        1-minute contract candles for the largest trades — the underlying price moves
        (e.g. one market's contract price falling from 97c to 67c to 54c across three
        real, liquid 1-minute bars, thousands of contracts of volume each) are genuine
        market behavior, not a data or conversion artifact.
      - **Neither result is close to gate-ready** (8.4 needs ≥200 trades; both strategies
        are far under that at default config on this data). This is exactly the kind of
        finding 8.2's new metrics exist to surface honestly rather than let a positive
        top-line PnL number pass unexamined.
- [x] 8.2 Metrics must include, beyond win rate and PnL: **trade concentration**
      (top-10 trades as a share of profit — Phase 1's run #8 was 122%), R-multiple
      distribution, max consecutive losses, and results under flat sizing. All four added
      to `backtest/metrics.py`'s `SegmentMetrics`: `top10_concentration_pct` (top-10
      trades' NET pnl as a fraction of TOTAL net profit — clarified from a first draft
      that used gross-winners-only as the denominator, which can mathematically never
      exceed 100%; the Phase-1-run-#8-122% framing only makes sense against total net
      profit), `max_consecutive_losses` (sorted by entry time, not settlement time, since
      early exits can reorder those), `r_multiples` (each trade's net PnL as a multiple of
      its own stake), and `net_pnl_at_flat_sizing_usd` (`flat_sizing_net_pnl_usd()`:
      recomputes PnL as if every trade used a fixed 1-contract size, isolating genuine
      per-trade edge from sizing-driven apparent profit — this is the exact metric that
      caught `level_break`'s Kelly-compounding artifact above). 16 new unit tests,
      known-answer style (hand-picked settlement sequences with a computed expected
      result, same discipline as the rest of this codebase's numeric tests).
- [x] 8.3 Walk-forward validation with a genuinely untouched holdout. Phase 1's test
      window was peeked 4 times during iteration, which is why its result could not be
      trusted. Decide the split in advance and do not re-run against it while tuning.

      **Pre-registered split: 2026-08-18 (75/25 of the archived window), fixed BEFORE any
      tuning and never moved after seeing test-segment results** — new `scripts/
      run_scalping_backtest.py` takes `--split-date` as a required arg specifically so this
      discipline is structural, not a promise. Three real, load-bearing bugs/gaps were
      found and fixed as prerequisites, none of which are strategy-config issues:

      1. **Archiver gap (operational, not code):** `archiver_loop.py`'s own log
         (`logs/archiver_loop.log`) shows it completed a normal pass and logged "Sleeping
         1800s..." at 2026-07-23 06:34, then nothing after — the loop window was closed (or
         the machine slept/restarted) and never relaunched, ~6 weeks of real time before this
         session. A separate, narrower process kept KXBTC/KXBTCD/KXBTC15M candles flowing
         through 2026-09-05, but not KXETH/KXETHD candles or hourly BTC-USD/ETH-USD
         `SpotCandle` rows — so `StrategyContext.spot_bars` was silently empty for the entire
         `KXBTC15M` era (2026-06-28 onward), structurally blocking `trend_scalp`/
         `level_break` regardless of config. Backfilled via new `scripts/backfill_spot_gap.py`
         — a live, unauthenticated, read-only call to Coinbase's public
         `/products/{symbol}/candles` endpoint (same fetch function `fetch_historical.py`
         already uses, just with a wider `hours` window to reach across the gap; explicitly
         approved as non-Kalshi, no-auth, no-orders traffic). 2,176 new hourly rows inserted
         (1,088 each BTC-USD/ETH-USD), closing the gap through 2026-09-06.
      2. **`DrawdownGuard` HALT is sticky-by-default and correctly so for live trading**
         (only a human `reset()` clears it) — **but that makes it wrong for backtesting a
         single long window**: one bad early stretch permanently zeroes
         `allows_new_entries()` for the rest of the run, so a 4-month backtest's trade sample
         becomes a statement about the guard, not the strategy. Found because `trend_scalp`'s
         710 train-segment trades all clustered before 2026-06-17 and then stopped dead — a
         HALT (57.7% all-time drawdown) tripped that day and never released. Fixed with a new
         `allow_reentry_after_halt` constructor flag (default `False`, live behavior
         untouched) that lets HALT recover like PAUSE once drawdown falls back under the
         threshold, for backtest callers only — `scripts/run_scalping_backtest.py` sets it
         explicitly, with an inline comment that it must never be set on a live path. New
         `ever_halted` property so a recovered run doesn't hide that HALT happened at all.
         4 new unit tests (`test_risk.py`): default stays sticky, reentry-enabled recovers,
         `ever_halted` survives recovery, flag is `False` when never tripped.
      3. **That 57.7% HALT itself turned out to be an equity-marking artifact, not real
         risk — root cause found AND fixed, in two passes.** Dug into it rather than
         accepting the number at face value: every position open at the HALT timestamp
         (2026-06-17) settled favorably 60 seconds later (same evaluation batch), and
         full-run drawdown computed from realized PnL alone is 0.14%, not 57.7%. At one
         timestep the engine evaluates every mapped series/strike, and ~24 correlated
         same-underlying-move strikes fired simultaneously in one batch.
         - **First pass (insufficient on its own):** each same-batch Kelly sizing call was
           reading the SAME stale pre-batch `equity`, snapshotted once at the top of the
           timestep, instead of being re-marked as the batch's own entries spent cash. Fixed
           by re-fetching cash + open positions immediately before each individual
           `size_binary_position()` call. Verified via a real run this genuinely shrinks
           per-entry bankroll as expected — but a dedicated regression test
           (`test_engine_concurrent_sizing.py`) proved it wasn't enough: EQUITY (cash + value
           of already-open positions) doesn't shrink when cash converts into a new position,
           so concurrent correlated entries in one batch still each saw ~the full original
           bankroll as "theirs," and `BacktestBroker.place_order`'s own
           `cost > self._cash` guard could only reject a too-large request outright — not
           downsize it — so most of a correlated batch got flatly turned away rather than
           appropriately sized down.
         - **Second pass (the actual fix):** size against AVAILABLE CASH, not total equity —
           conservative, and matches what a real margin check would allow spending (money
           already committed to a sibling position isn't free to spend on a new one). Now a
           second/third correlated entry in the same batch sizes down instead of being
           rejected outright. `max_drawdown_pct` dropped materially on rerun (see below) —
           real evidence the fix reduces phantom correlated over-exposure, not just a
           plausible-sounding change. 1 new engine-level regression test
           (`test_engine_concurrent_sizing.py`): 6 identical correlated candidates against a
           small bankroll must show non-increasing per-entry quantities, more than one
           opportunity taken (not all-or-nothing), and total spend within starting cash —
           confirmed to fail with either the original stale-equity bug OR the
           re-marked-but-still-equity-based intermediate fix, and pass only with the final
           cash-based version (checked by hand, temporarily reintroducing each prior bug and
           re-running this test before committing to the final version). `net_pnl_at_flat_
           sizing_usd` and win-rate-margin were never affected by any version of this bug
           (they don't depend on the equity-curve marking path).

      **Real walk-forward results against the pre-registered 2026-08-18 split, WITH the
      cash-based sizing fix** (same 68-day accumulated window, $200 starting cash,
      `eval_stride_s=900`, `allow_reentry_after_halt=True`):
      - `trend_scalp` (loosened train-only config: `min_trend_zscore=0.15, min_touches=1,
        level_tolerance_pct=0.008, lookback_bars=10` — chosen using ONLY train-segment
        output, before the test segment was ever inspected): **[train] 544 trades** (down
        from 710 pre-fix — fewer, more honestly-sized entries), **win_rate=76.5% vs
        breakeven=66.6% (margin +9.9%, up from +7.5%), net_pnl=+$3914.13,
        flat_sizing_net_pnl=+$55.26 (still positive — this config's edge is not purely a
        sizing effect), max_dd=46.7%** (down from 58.1% pre-fix — real evidence the fix
        reduced overstated correlated exposure). Still HALTs (46.2% all-time drawdown, just
        above the 40% threshold) and **[test] zero trades.**
      - `level_break` (default config, unchanged): **[train] 110 trades** (unchanged — this
        config's entries are apparently never part of a large correlated batch),
        **win_rate=70.9% vs breakeven=67.1% (margin +3.9%, unchanged), net_pnl=+$785.79**
        (down from +$1032.12 pre-fix — the fix removed some sizing-inflated PnL, exactly as
        intended), **flat_sizing_net_pnl=+$4.58 (unchanged), max_dd=43.8%** (down from 50.2%
        pre-fix). Still HALTs (42.2% all-time drawdown, now only marginally above 40%) and
        **[test] zero trades.**
      - **Both strategies still produced zero test-segment trades against the genuinely
        untouched holdout, even with the sizing fix.** The sizing fix is real and verified
        (drawdown dropped materially in both runs, for a documented reason, not a fluke) —
        but it wasn't sufficient by itself to clear the 40% HALT threshold in either run, so
        the SEPARATE circularity in finding #2 (a HALTed run can't recover without new
        entries, and can't take new entries without first recovering) remains the actual
        blocker for walk-forward validation on this specific dataset. **8.3's actual
        finding: the Kelly cross-position sizing gap was real, found, fixed, and verified —
        but walk-forward validation still cannot be honestly completed on this dataset until
        either (a) the DrawdownGuard reentry circularity in finding #2 is resolved (e.g. a
        backtest-only recovery path that doesn't require an actual new entry to observe
        recovered equity), or (b) config tuning targets producing trades spread more evenly
        across the whole window rather than clustering into one early, high-drawdown
        stretch.**
- [x] 8.4 **Gate criteria, fixed before seeing results:** win rate clears the computed
      cost floor with margin; Sharpe > 1.0; no single trade > 10% of profit;
      max drawdown < 20%; ≥200 trades. Miss any ⇒ no live capital.

      **Formally checked against the walk-forward test segment (the only segment the gate is
      allowed to read) — both strategies fail immediately and decisively on trade count:**
      - `trend_scalp`: 0 test trades — fails ≥200 (fails every other criterion vacuously
        too, since none are computable with zero trades).
      - `level_break`: 0 test trades — same failure.
      - Train-segment numbers (544 and 110 trades respectively, post-sizing-fix) are NOT
        eligible for the gate by design (D6/8.3's whole point) and are reported above for
        tuning transparency only, not as a gate input.
      - **Gate result: FAIL for both strategies.** Not close, not borderline — zero
        qualifying trades is an unambiguous miss on the ≥200-trade criterion, and 8.3's
        write-up traces exactly why (dataset-clustering interacting with the DrawdownGuard
        HALT circularity — the Kelly sizing gap that was ALSO a real, separate bug has since
        been fixed and verified, and materially reduced train-segment drawdown in both runs,
        but did not by itself clear the 40% HALT threshold), so this isn't a mysterious dead
        end — it's a known, specific blocker with two named ways to unblock it.
- [ ] 8.5 If the gate fails: funding carry, then weather, then park. **Do not tune into
      the holdout.** Parking is an acceptable, expected outcome. **Gate failed for both
      trend_scalp and level_break (8.4) — next per this task's own ordering is
      `funding_carry` (§6.3, already built and unit-tested, never backtested).** Not yet
      run: `funding_carry` doesn't fit `BacktestEngine`'s single-instrument settle-to-expiry
      model (it's a two-leg hedge across a Kalshi contract and a funding-bearing perp
      position, tasks.md 6.3's own scope note) — backtesting it needs either a dedicated
      two-leg simulator or a materially different engine path, not attempted in this
      session.

      **§8 checkpoint:** full suite green (348 passed — 343 at 8.1/8.2, +4 `DrawdownGuard`
      reentry tests, +1 concurrent-sizing regression test this pass), ruff + pyright clean.
      Real walk-forward validation executed against a pre-registered, never-peeked holdout
      split — both strategies formally failed the 8.4 gate on trade count, for a root cause
      that's now understood in full (not a mystery, and not left as a single unfixed
      hand-wave): a real Kelly cross-position sizing gap (concurrent same-timestep correlated
      entries didn't share a capital ledger) was found, fixed in two passes (first re-marking
      equity per entry, then correctly switching the sizing base to available cash), and
      verified to materially reduce overstated drawdown in both real reruns (trend_scalp
      58.1%→46.7%, level_break 50.2%→43.8%) — but a SEPARATE DrawdownGuard reentry
      circularity (can't recover from HALT without a new entry's PnL moving equity, can't
      take a new entry without first recovering) remains the actual blocker for producing any
      test-segment trades on this specific dataset. Three live, non-Kalshi network calls this
      session: the Ollama veto smoke test (§7, prior) and the Coinbase public-candle backfill
      (§8.3, this pass, run once) — both explicitly approved, neither touches Kalshi's demo or
      production endpoints. No live/demo Kalshi network call anywhere in §8. No git commit
      made.

## 9. Frontend

**Reprioritized ahead of §4-§7 by explicit user decision (2026-09-05).** Built now
against what already exists (backtest runs, signals incl. HOLDs, simulated trades,
data coverage) rather than waiting for the authenticated client/risk layer/strategies.
Live-trading views (positions, orders, brackets, funding, liquidation distance, AI
commentary) have no data source yet and render as explicit placeholder panels — not
faked, not hidden. `src/kalshi_bot/web/` (app.py, queries.py, control_state.py,
templates/, static/) + `scripts/start_dashboard.py` + `start_dashboard.bat`.

- [x] 9.1 FastAPI + Jinja + HTMX app, no build step. `create_app()` in
      `src/kalshi_bot/web/app.py`; `htmx.org` loaded from a CDN `<script>` tag, no
      bundler.
- [x] 9.2 `start_dashboard.bat` → `scripts/start_dashboard.py`: launches uvicorn on
      127.0.0.1, opens the browser. **Trading starts stopped** — `ControlPanel` in
      `control_state.py` defaults to `armed=False`; Start is an explicit POST from the
      UI. No live-trading process exists yet to actually arm (§4-§7), so arming records
      operator intent honestly rather than pretending a bot started.
- [x] 9.3 (partial — real data where it exists, placeholders where it doesn't). Real:
      equity curve (reconstructed from settled `SimulatedTrade` rows), recent decisions
      **including HOLDs and reasons** (`SignalRecord`), backtest run metrics, BTC data
      coverage. Placeholder (§4-§7 not built): live positions/PnL, open orders/brackets,
      guard state, funding countdown, liquidation distance, AI commentary.
- [x] 9.4 Kill switch — prominent button, one click, sets `halted=True` via
      `ControlPanel.kill()`. Not yet wired to `EmergencyControl` because that class
      doesn't exist until §5 (risk layer) is built; the control-state plumbing is ready
      for it.
- [ ] 9.5 Live updates via WebSocket or HTMX polling — not done; current views are
      request-on-load. Revisit once §4-§7 produce data that actually changes in
      real time.
- [x] 9.6 Auth: binds to `127.0.0.1` by default in `start_dashboard.py`; passing
      `--host` other than loopback refuses to start unless `DASHBOARD_AUTH_SECRET` is
      set (the setting already existed in `config/settings.py`). No request-level auth
      middleware is implemented yet — only the bind-address gate.
- [ ] 9.7 Docusaurus's fate (open question O4) — not decided; Docusaurus is still the
      docs surface, dashboard is a separate `start_dashboard.bat`, not yet unified.

**Known correctness bug found and fixed during this work:** `ControlPanel.arm()`/
`kill()` initially deadlocked — each acquired `self._lock` then called
`self.snapshot()`, which tried to acquire the same non-reentrant lock again. Every
POST to `/control/arm` or `/control/kill` hung forever. Fixed by constructing the
returned `ControlState` directly instead of calling back into `snapshot()`. Caught by
testing the real HTTP routes end-to-end (GET routes alone would not have surfaced it).

**Also found and fixed:** `coverage_report()` does two full table scans per series
(no index on `series_ticker`+`period_minutes`); over the current ~17M-row `candles`
table that's 60-90s for the three BTC series combined — unusable as a per-request
call. Fixed with a background-thread cache in `queries.py`
(`refresh_coverage_cache`/`cached_btc_coverage`, 120s TTL, warmed on startup and
refreshed on a timer) so page loads never block on it; the coverage panel shows a
"computing..." state only on the very first request after a cold start.

## 10. Paper → live

- [ ] 10.1 Paper trade event contracts ≥2 weeks against live data with simulated fills.
- [ ] 10.2 Compare paper results to backtest expectations. Divergence here means the
      backtest is still lying — investigate before proceeding, do not rationalize.
- [ ] 10.3 Live event contracts, minimum size, $200 bankroll.
- [ ] 10.4 Perps in paper only, ≥2 weeks, brackets exercised and verified — including a
      deliberate process-kill test proving the server-side stop survives the bot dying.
- [ ] 10.5 Live perps at 2x max, only after 10.3 and 10.4 both hold up.
