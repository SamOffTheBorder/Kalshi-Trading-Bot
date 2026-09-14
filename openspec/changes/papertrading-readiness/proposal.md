## Why

`strategy-lab-multi-account` finished the machinery: registry-selected
strategies, a causal `StrategyContext` builder, a `PerpPaperAdapter`, a
multi-account launcher, and dashboard comparison views all work end-to-end
and are tested (861 passing). None of that produces a single real paper
decision or fill today, because every domain is blocked one step earlier, by
configuration and data state rather than missing code:

- **Prediction.** Every crypto series in `DEFAULT_CRYPTO_REGISTRY` sits at
  `backtest` (BTC, ETH) or `observe` (SOL, XRP) — none at `shadow` or `paper`.
  `run_preflight` correctly refuses all of them. Worse, `CryptoInstrumentConfig
  .lifecycle` is typed `Literal["observe", "backtest", "paper", "live"]` —
  **`"shadow"` is not a legal value of the registry's own lifecycle field**,
  even though `LifecycleState` (`config/lifecycle.py`) defines it and the rest
  of the system understands it. An operator cannot promote an asset to shadow
  today without a type change first. Separately, `DatasetManifest` has zero
  rows — no asset has a frozen, `source_native` manifest — so even a
  registry promoted to `paper` would record decisions and refuse every fill
  (`reconstructed_data_not_admissible` / `no_frozen_admission_report`).
- **Perpetuals.** `DiscoveryResult` has zero rows where `instrument="perp"`.
  `evaluate_perp_admission` refuses every asset with `no_discovery_snapshot`
  before any other check runs. Marks are additionally 2 days stale against a
  120s freshness requirement. The cause is narrower than it looks:
  `discovery/service.py` already has a complete, tested `PerpDiscovery` class
  mirroring `EventSeriesDiscovery` exactly (`refresh(asset, session)`,
  same persistence path) — it has simply never been called from anywhere
  outside its own unit tests. `scripts/discover_crypto_series.py` is the
  working event-side entrypoint; no perp-side equivalent exists.
- **Sports.** `scripts/run_paper.py`'s `_build_adapter` only branches on
  `domain in {"prediction", "perp"}`; `--domain sports` hits the
  `SystemExit` fallback despite `SportsPaperAdapter` existing and being fully
  unit-tested. This is a wiring gap, not a research gap — but even wired,
  `evaluate_sports_paper_admission` hard-refuses until a feasibility report
  says `research_promising`, and that report has never been run
  (`sports-market-feasibility` 4.4 and `sports-evidence-and-flow-research`
  4.5 are both still open, and rightly so — they need weeks of captured data
  this change does not shortcut).

This proposal is narrow on purpose: it operationalizes the concrete,
already-known blockers standing between "machinery complete" and "first real
paper decision," for the two domains where the remaining work is
configuration/plumbing (prediction, perpetuals), and closes the CLI wiring
gap for sports so that domain is ready the moment its feasibility report
lands. It does **not** re-scope or duplicate `multi-venue-paper-trading`,
`v2-perps-scalping-and-frontend`, `sports-market-feasibility`, or
`sports-evidence-and-flow-research` — those own backtests, coverage reports,
and the sports research verdict, and stay authoritative for that work.

## What Changes

- **Fix the registry's lifecycle type gap.** Add `"shadow"` to
  `CryptoInstrumentConfig`'s `LifecycleMode` (and `CryptoPerpConfig` if it has
  an equivalent), so an operator can actually express "promote BTC 15m to
  shadow" without a code change becoming a prerequisite of a config change.
- **Add a manifest-freezing operator command.** A script
  (`scripts/freeze_manifest.py` or equivalent) that runs the existing
  `DatasetManifest` construction path for one asset/cadence against currently
  captured data and writes the frozen, `source_native`-checked row —
  reachable without hand-writing a manifest row. This is the one prerequisite
  every prediction paper-mode fill needs and today has no operator-facing
  entrypoint at all.
- **Promote one prediction series to `shadow`, deliberately.** After the type
  fix, flip exactly one series (recommend BTC 15m — the registry's most
  mature, currently `backtest`) to `shadow` as a real operator decision
  recorded in this change, not left implicit. This produces the first actual
  shadow-mode decisions (no fills) under the completed strategy-lab
  machinery.
- **Add `scripts/discover_crypto_perps.py`.** A perp-side counterpart to
  `scripts/discover_crypto_series.py`, calling the already-built
  `PerpDiscovery.refresh()` for each registry asset with a `perp` config,
  producing the first non-empty `DiscoveryResult` rows for
  `instrument="perp"` and clearing `no_discovery_snapshot`.
- **Wire `--domain sports` into `run_paper.py`.** Extend `_build_adapter` to
  construct `SportsPaperAdapter` the same way prediction/perp are
  constructed. This is pure plumbing — it does not touch
  `evaluate_sports_paper_admission`'s gate, which stays refusing until the
  feasibility report says `research_promising`.
- **Publish a readiness matrix** (dashboard panel or doc, reusing the
  `market_area.html` admission table pattern already built for prediction)
  showing, per domain, which of these prerequisites are met — so "how close
  are we" is answerable by looking at the dashboard instead of re-running
  ad hoc SQL queries against the paper DB.

## Impact

- Affected specs: `crypto-registry-lifecycle` (new — the `shadow` literal
  fix), `manifest-freezing-operator-flow` (new), `perp-discovery-pass` (new),
  `sports-paper-cli-wiring` (new).
- Affected code: `config/crypto_registry.py`, new `scripts/freeze_manifest.py`,
  new `scripts/discover_crypto_perps.py`, `scripts/run_paper.py`
  (`_build_adapter`), `web/queries.py` / `web/templates/market_area.html`
  (readiness matrix).
- **No change to any admission gate's refusal logic.** This proposal makes
  the existing gates reachable and satisfiable through normal operator
  action; it does not loosen `reconstructed_data_not_admissible`,
  `no_discovery_snapshot`, or `evaluate_sports_paper_admission`'s
  `research_promising` requirement.
- **`PAPER_TRADING=true` and demo-env requirements are untouched.** Nothing
  here introduces a live-order path.
- Explicitly out of scope, owned elsewhere: BTC/ETH/SOL/XRP coverage reports
  and asset-isolated backtests (`multi-venue-paper-trading` §5.6, §7.x);
  perpetual shadow validation and bracket drills (`multi-venue-paper-trading`
  §9.10); the sports feasibility verdict itself (`sports-market-feasibility`
  §4.3–4.4, `sports-evidence-and-flow-research` §4.5); the ≥2-week paper
  soak and live-graduation decisions (`v2-perps-scalping-and-frontend`
  §10.1–10.5).

## Open Questions

1. **Which series gets the first shadow promotion?** Recommendation: BTC
   15m. It is the only series with `btc=True` special-casing in the
   registry, has the deepest spot-candle history (7,520 rows), and is the
   subject of the most existing validation work
   (`kxbtc15m-validation-rebuild`). Promoting a thinner series (SOL, XRP)
   first would produce shadow decisions with less signal about whether the
   pipeline itself is healthy.
2. **Does freezing a manifest from currently-captured (BRTI 2.9-day, stale)
   data produce a meaningful `source_native` manifest, or just a technically
   valid but data-thin one?** Recommendation: freeze it anyway and let the
   dashboard readiness matrix show the manifest as present but the
   settlement-aware strategies (`settlement_prob`, `settlement_trend`) as
   still starved of fresh BRTI — the manifest and the capture-freshness
   problem are separate gates and should stay visibly separate rather than
   conflated into one blocker.
3. **Should `discover_crypto_perps.py` be merged into
   `discover_crypto_series.py` as a `--instrument perp` flag instead of a
   separate script?** Recommendation: separate script, matching the existing
   one-script-per-instrument-type pattern, since `PerpDiscovery.refresh`
   takes an asset (no cadence loop) and the two report shapes already differ
   enough that a shared flag would need its own branching anyway.

## Model complexity

| Stage | Recommended | Notes |
|---|---|---|
| Registry `LifecycleMode` fix + shadow promotion | Sonnet | Type literal change plus a deliberate, documented config edit. |
| Manifest-freezing script | Sonnet | Wraps an existing, tested construction path in an operator entrypoint. |
| Perp discovery script | Sonnet | `PerpDiscovery` is already built and tested; this mirrors `discover_crypto_series.py`'s existing shape 1:1. |
| Sports CLI wiring | Sonnet | Mirrors the existing prediction/perp branches in `_build_adapter`. |
| Readiness matrix | Sonnet | Read-only query + template, follows `market_area.html`'s existing admission-table pattern. |
| Tests | Sonnet | Known-answer style, matching existing suite conventions. |

Escalate to Opus only if implementation reveals `PerpDiscovery` needs
behavior changes beyond a calling script, or if the manifest-freezing
script's `source_native` check needs new provenance logic rather than reuse
of `data/manifests.py`.
