## Context

`strategy-lab-multi-account` closed the code gap: a strategy is selectable,
a `StrategyContext` is causally assembled, a perp adapter exists, accounts
are isolated, and the dashboard compares runs. Nobody has produced a single
paper decision since, because every domain's *first* gate — not a deep one,
the very first one `run_preflight` or `evaluate_perp_admission` checks — is
unmet by configuration or missing data, not by missing code. This change's
job is to make each first gate reachable through a normal operator action,
without touching what the gate requires.

## Goals / Non-Goals

**Goals**
- An operator can promote a crypto series to `shadow` without a type error.
- An operator can freeze a manifest from currently captured data through a
  script, not a hand-written `ManifestSpec`.
- Perp `DiscoveryResult` rows exist, because a script calls the already-built
  `PerpDiscovery`.
- `run_paper.py --domain sports` constructs an adapter instead of exiting.
- The dashboard shows, per domain, which prerequisite is met and which is
  not — replacing ad hoc SQL as the way to answer "how close are we."

**Non-Goals**
- Loosening any gate's refusal condition. `reconstructed_data_not_admissible`,
  `no_discovery_snapshot`, and `evaluate_sports_paper_admission`'s
  `research_promising` requirement are unchanged.
- Producing the sports feasibility verdict — owned by
  `sports-market-feasibility` §4.3–4.4 and `sports-evidence-and-flow-research`
  §4.5.
- Coverage/source-comparison reports or asset-isolated backtests — owned by
  `multi-venue-paper-trading` §5.6, §7.x.
- Deciding whether BTC 15m's shadow decisions are *good* — this change
  produces the decisions; judging them is separate, later work.

## Decisions

### 1. `LifecycleMode` gets `"shadow"` added, not replaced

`config/crypto_registry.py`'s `LifecycleMode` is
`Literal["observe", "backtest", "paper", "live"]`. `config/lifecycle.py`'s
`LifecycleState` already has `"shadow"`. The fix is additive — extend the
registry's literal to match `LifecycleState`'s vocabulary — not a rename or
a switch to importing `LifecycleState` directly, since `CryptoInstrumentConfig`
also needs `"observe"`/`"backtest"` which `LifecycleState` calls the same
thing, so no semantic reconciliation is needed, only the missing value.
`validate_registry`'s lifecycle check (`config/crypto_registry.py:138`)
already enumerates the allowed set inline and needs the same addition or it
will reject a `shadow` row that the type system now permits.

### 2. Manifest freezing reuses `ManifestSpec`/`persist_manifest` verbatim

`data/manifests.py` already has everything needed: `ManifestSpec` (asset,
source, time range, parser/feature/code versions, `partition_provenance`),
`manifest_hash`, `persist_manifest` (idempotent — returns the existing row
for an identical spec rather than duplicating). The script's only job is to
**honestly populate** a `ManifestSpec` from what is actually captured today
— real `start_ts`/`end_ts` bounds from the queried table, a real
`partition_provenance` per source (so `classify_provenance` genuinely
returns `source_native` rather than being forced to), and a real
`coverage_summary`. If the honestly-computed provenance is not
`source_native` for the asset being frozen, the script freezes the manifest
anyway (freezing is not the same claim as fill-eligibility) and the
resulting manifest correctly continues to block fills — that is
`reconstructed_data_not_admissible` doing its job, not a bug in this script.

### 3. Perp discovery is a new script, not new discovery logic

`discovery/service.py`'s `PerpDiscovery` class already exists, is unit
tested, and has the exact same shape as `EventSeriesDiscovery`
(`refresh(asset, session) -> DiscoverySnapshot | None`, same
`DiscoveryResult` persistence). `scripts/discover_crypto_perps.py` mirrors
`scripts/discover_crypto_series.py` line for line: same
`KalshiPublicClient`, same registry iteration, same JSON report shape,
substituting `PerpDiscovery` for `EventSeriesDiscovery` and iterating assets
with a non-`None` `.perp` instead of `.event_instruments`. No change to
`discovery/service.py` itself is anticipated.

### 4. Sports CLI wiring changes only `_build_adapter`'s branch, not the gate

`scripts/run_paper.py:_build_adapter` currently handles
`domain in {"prediction", "perp"}` and raises `SystemExit` otherwise. Add a
third branch constructing `SportsPaperAdapter` the same way the other two
domains are constructed (same session factory, settings, run id pattern).
`evaluate_sports_paper_admission` is untouched — with no feasibility report
at `research_promising`, `SportsPaperAdapter` will run and refuse
admissions exactly as the prediction/perp adapters do today for a
`gate_failed` strategy: recording the refusal, producing no fills. This is
deliberate — wiring the CLI now means sports is paper-run-capable the
instant its feasibility report clears, with no code change needed at that
moment.

### 5. Readiness matrix reuses `market_area.html`'s admission-table pattern

The per-asset admission table already built for prediction
(`market_area.html` "Per-asset admission" section, fed by `web/queries.py`)
is the template. Extend the same query shape to cover: registry lifecycle
per series, manifest-frozen boolean, perp discovery-snapshot boolean,
mark/BRTI freshness, and (for sports) feasibility-report outcome. This is a
read-only aggregation over existing tables (`DatasetManifest`,
`DiscoveryResult`, `PerpMarkObservation`, `BRTIObservation`) plus the
registry — no new write path.

## Risks / Trade-offs

- **A frozen manifest built from today's thin/stale BRTI (2.9 days, 24.6h
  stale) is technically valid but not informative.** Accepted: the manifest
  and freshness are separate, visible gates on the readiness matrix per Open
  Question 2 in the proposal; conflating them would hide which one is
  actually blocking a given asset.
- **Promoting BTC 15m to `shadow` is a real operator decision with no
  reversal cost** (shadow records decisions, never fills) but should not be
  silent. It is recorded as an explicit task in this change, with the
  reasoning captured in the proposal rather than buried in a config diff.
- **Wiring sports into the CLI before its feasibility report exists risks
  looking like sports is "ready."** Mitigated by the dashboard readiness
  matrix showing the feasibility-report outcome explicitly — a wired but
  gated domain reads as gated, not ready.

## Migration Plan

No schema migration. `LifecycleMode`'s literal extension and
`validate_registry`'s allowed-set update are additive and backward
compatible with every existing registry row (none currently use `shadow`,
so no existing data becomes invalid). The manifest and discovery scripts are
new, additive entrypoints. The readiness matrix is a new read path.

## Open Questions

Carried from `proposal.md` — see that file for the full list and
recommendations.
