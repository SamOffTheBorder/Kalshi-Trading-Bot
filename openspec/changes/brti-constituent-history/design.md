## Context

`signals/settlement_window.py` resolves KXBTC15M as:

```
YES  iff  mean(BRTI over the 60 s ending at close_ts)
          >=  mean(BRTI over the 60 s ending at open_ts)
```

Two consequences drive every decision below. First, the quantity that matters
is a **60-second mean of a 1-second index**, not a tick and not a 1-minute
OHLC bar — so a proxy must be evaluated at that timescale, and 1-minute
candles are too coarse to reconstruct it faithfully. Second, these contracts
settle near a coin flip; the difference between YES and NO is frequently a few
dollars of index level. A proxy error that would be negligible for a
directional model is decisive here.

The project already has the provenance machinery this change needs:
`data/provenance.py`, `data/manifests.py`, `data/quality.py`,
`data/source_compare.py` (which already emits `quote_currency_mismatch`), and
a `SourceRole` literal in `data/external_sources.py`. This change extends
those rather than introducing a parallel path.

## Goals / Non-Goals

**Goals**
- Years of free, USD-quoted, constituent-venue history usable for research.
- A reconstruction whose error against true BRTI is *measured and recorded*,
  not asserted.
- A mechanical, fail-closed boundary preventing reconstructed data from
  reaching a promotion gate.

**Non-Goals**
- Reproducing BRTI exactly. CF Benchmarks consolidates full order books with a
  licensed methodology; trade prints cannot reproduce that, and this change
  does not pretend otherwise.
- Replacing live BRTI capture. Reconstruction complements capture; it never
  substitutes for it in a validation run.
- Any TradingView automation.

## Decisions

### D1 — Kraken first, Coinbase second; Binance stays but is reclassified

Kraken is the single best free source available: a BRTI constituent, USD-quoted,
with complete trade history from 2013-10-06 published for direct download.
Coinbase adds the second constituent and the largest US book. Composing two
constituents tracks the consolidated index materially better than either
alone.

Binance mappings in `external_sources.py` remain (they are useful for
volatility regimes and are the deepest 1s-resolution archive), but they are
**not** eligible to feed the synthetic BRTI composer: `BTCUSDT` is a different
quote asset with its own basis, and Binance is not an index constituent.

*Alternative rejected:* TradingView. Export requires a paid plan, caps at
40,000 bars (≈28 days at 1-minute), has no programmatic API, and its bars are
already a lossy derivative of the exchange feeds obtainable directly. The
existing `manual_comparison` boundary is the correct home for it.

### D2 — A new `constituent` source role, not a reuse of `primary`

`SourceRole` becomes `primary | secondary | constituent | manual_comparison`.
`constituent` asserts something `primary` does not: that the venue is a
documented input to the settlement index. Only `constituent` sources may enter
the composer. This keeps "reproducible archive" and "index input" as separate
claims, so adding a new deep archive never silently makes it index-eligible.

### D3 — Compose from trades onto a 1-second grid; never forward-fill across a gap

The composer emits a 1-second series to match BRTI's cadence. For each second
it takes the last trade price per constituent, then combines across
constituents by **median** (not mean): medians resist a single venue's outlier
print or a stale book, which is the dominant failure mode in thin hours.

Where a constituent has no print in a second, it contributes nothing for that
second rather than carrying its last value forward — a carried value is a
fabricated observation, and `data/quality.py` already treats gaps as
first-class. Every emitted second records `contributor_count`. A second with
`contributor_count == 0` is a gap, not a value.

*Alternative rejected:* volume-weighted mean across venues. It is closer to how
some indices work, but it is more sensitive to a single large print and
requires trusting per-venue volume normalization across four different
reporting conventions.

### D4 — Measure error at 60 seconds, on the resolution rule itself

The reconstruction-error report computes, over windows where both true BRTI and
synthetic coverage exist:

1. `mean_abs_diff` of the level (a sanity check), and
2. **`resolution_agreement`** — the fraction of simulated 15-minute contracts
   where the synthetic series and true BRTI produce the *same YES/NO outcome*
   under the `settlement_window` rule.

(2) is the number that matters. A proxy can track the level within a few
dollars and still disagree on outcome whenever the 60-second means are close,
which is exactly the population these contracts live in. Reporting only price
error would flatter the proxy precisely where it is weakest.

This measurement requires captured BRTI, which requires `KALSHI_KEY_ID`. Until
a measurement exists the reconstruction is **unmeasured**, and D5 treats
unmeasured as diagnostic-only.

### D5 — Fail-closed manifest classification

`DatasetManifest` gains `provenance_class: "source_native" | "reconstructed"`
and `reconstruction_error: ReconstructionError | None`.

The classification rule is deliberately inverted from the convenient default:
a manifest is `source_native` only if **every** partition is source-native.
Any reconstructed partition, an unrecognized provenance, or a missing
classification makes it `reconstructed`. Forgetting to label something
therefore blocks promotion rather than permitting it.

Enforcement lands at the point that already exists rather than a new gate:
`run_preflight()` in `execution/orchestrator.py` computes `may_fill` from
`_report_ok(asset_id)`. That check is extended so a frozen admission report
whose manifest is `reconstructed` fails, with reason
`reconstructed_data_not_admissible`. The asset still runs — admitted for
decision recording — so research continues; only *fills* are refused.

### D6 — Reconstructed data may reject a strategy, never admit one

Stated as an asymmetry because the epistemics are asymmetric. A strategy that
loses money across five years of constituent history is falsified cheaply and
credibly — proxy error is not what killed it. A strategy that *wins* on proxy
data has shown only that it wins on a series that is not the settlement index.
Backtests on a `reconstructed` manifest are therefore reported as
`diagnostic_only`, with negative results actionable and positive results
carrying an explicit "requires validation against captured BRTI" status.

## Risks / Trade-offs

- **The proxy may be too weak at 60 s to be worth its complexity.** Mitigation:
  D4 measures this directly and early. If `resolution_agreement` is near
  chance, the honest outcome is to use the data for volatility/regime work
  only, and the report will say so rather than the data quietly being trusted.
- **Error is measurable only where captured BRTI exists** — currently nowhere,
  and only forward from first capture. Reconstruction quality in 2019 cannot be
  verified from a 2026 sample; regime shifts and constituent-set changes make
  extrapolation weak. Mitigation: this is exactly why reconstructed manifests
  never admit, and the limitation is recorded in the report rather than
  reasoned around.
- **Constituent set drift.** The six platforms are not fixed for all history;
  itBit/LMAX in particular are less accessible. Mitigation: `contributor_count`
  is persisted per second, so a window built from two venues is never
  mistaken for one built from six.
- **Storage.** Full tick history for four assets across two venues is large.
  Mitigation: raw artifacts are retained compressed as fetched; the composed
  1-second series is the derived product, and normalization is per-partition
  so a subset can be built without the whole archive.

## Migration Plan

Additive throughout; no existing table is rewritten.

1. New tables/columns for constituent artifacts, the reconstructed series, and
   the manifest classification fields. Existing manifests read back as
   `source_native` only if all their partitions are source-native — Binance and
   Kalshi partitions are, so historical manifests keep their meaning.
2. `SourceRole` gains a variant; existing `primary`/`manual_comparison` values
   are unaffected.
3. The preflight change is a tightening. Since no admission report exists in
   the repository today, nothing currently-passing begins to fail.

## Open Questions

- Which constituent pair is sufficient? The plan starts with Kraken + Coinbase
  and adds Bitstamp/Gemini only if `resolution_agreement` is materially
  improved by them — measured, not assumed.
- Should the composer weight by book depth rather than take an unweighted
  median across venues? Depth is closer to the real methodology but is not
  available in free historical trade archives; deferred until the two-venue
  agreement number shows whether it would matter.
- What `resolution_agreement` threshold, if any, should let a reconstructed
  manifest support a *shadow*-mode promotion? Left open deliberately: the
  number should be chosen after the first measurement exists, not before.
