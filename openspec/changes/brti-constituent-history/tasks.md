## 1. Provenance boundary first

Deliberately ordered before any acquisition work: the boundary is the part
that makes the rest safe, and building it first means no reconstructed row
can ever exist before the rule that contains it.

- [ ] 1.1 Add `provenance_class` (`source_native` | `reconstructed`) and `reconstruction_error` fields to the dataset-manifest model and storage, defaulting to `reconstructed` when absent.
- [ ] 1.2 Implement fail-closed classification: `source_native` only when every enumerated partition is source-native; unknown or unrecognized provenance yields `reconstructed`.
- [ ] 1.3 Extend `run_preflight()` in `execution/orchestrator.py` so a frozen admission report backed by a `reconstructed` manifest fails `_report_ok`, with reason `reconstructed_data_not_admissible`, while the asset remains admitted for decision recording.
- [ ] 1.4 Add tests: mixed manifest classifies `reconstructed`; unclassified manifest classifies `reconstructed`; preflight refuses fills but still records decisions; a `source_native` manifest still permits fills.
- [ ] 1.5 Add a test asserting the default-on-omission behavior directly — a manifest constructed without the new field must not be admissible.

## 2. Constituent source role and mappings

- [ ] 2.1 Extend `SourceRole` in `data/external_sources.py` with `constituent`; add the target-index identity to constituent mappings.
- [ ] 2.2 Register Kraken BTC/ETH/SOL/XRP USD mappings as `constituent` against BRTI, with native symbols and USD quote currency.
- [ ] 2.3 Register Coinbase BTC/ETH/SOL/XRP USD mappings as `constituent` against BRTI, alongside its existing secondary role.
- [ ] 2.4 Register Bitstamp and Gemini constituent mappings behind the adapter seam without implementing acquisition yet.
- [ ] 2.5 Add tests proving Binance USDT mappings are refused the `constituent` role and that role assignment is not inferable from coverage depth.

## 3. Kraken acquisition

- [ ] 3.1 Implement `data/kraken_public.py`: a read-only client resolving Kraken's published historical trade/OHLCVT download artifacts for the four assets.
- [ ] 3.2 Implement idempotent, resumable foreground download with raw-artifact provenance recording (content hash, size, URL, retrieval time, parser version).
- [ ] 3.3 Record integrity status honestly — `unverified` where Kraken publishes no sidecar checksum; never record unverified artifacts as checksum-verified.
- [ ] 3.4 Normalize Kraken trades into typed observations with `observed_at` / `available_at`, without forward fills.
- [ ] 3.5 Add fixture tests: malformed CSV, empty archive, duplicate trade IDs, non-monotonic timestamps, mixed time units, partial download resume.

## 4. Coinbase acquisition

- [ ] 4.1 Extend `data/coinbase_public.py` to acquire USD trade history for the four assets at the depth its public API allows, preserving raw responses.
- [ ] 4.2 Record missing buckets as coverage gaps rather than manufacturing candles (reuse the existing secondary-adapter behavior).
- [ ] 4.3 Implement rate-limit-aware bounded pagination with a documented ceiling; no unbounded backfill loop.
- [ ] 4.4 Add fixture tests for gap reporting, rate-limit backoff, and idempotent re-import.

## 5. Synthetic BRTI composer

- [ ] 5.1 Implement `data/synthetic_brti.py`: refuse any input that is not `constituent`-roled with a matching quote currency; report the refusal rather than silently dropping the input.
- [ ] 5.2 Emit a one-second grid; per second take each constituent's last trade price and combine by median across contributing constituents.
- [ ] 5.3 Never forward-fill across a silent second; record `contributor_count` on every emitted second and a coverage gap where it would be zero.
- [ ] 5.4 Persist output with `provenance="reconstructed_index"` in a store distinct from `brti_observations`, recording the contributing venue set.
- [ ] 5.5 Add a guard test proving reconstructed values cannot be returned by the captured-BRTI read path, and that a capture-only request over a reconstruction-covered window reports insufficient data.
- [ ] 5.6 Add composition tests: single-venue seconds, two-venue medians, all-silent seconds, outlier print resistance, venue with a stale run of prints.

## 6. Reconstruction-error measurement

- [ ] 6.1 Implement the error report over windows where captured BRTI and reconstruction overlap: mean and max absolute level difference.
- [ ] 6.2 Implement `resolution_agreement` — the fraction of simulated 15-minute contracts where reconstruction and captured BRTI agree on settlement outcome under the `signals/settlement_window.py` rule.
- [ ] 6.3 Report `unmeasured` where no overlap exists; never emit a passing quality status for an unmeasured reconstruction.
- [ ] 6.4 Write the measurement (or `unmeasured`) into the dataset manifest and into run reports.
- [ ] 6.5 Add tests: a reconstruction that tracks level closely but disagrees on near-coin-flip outcomes must show high level agreement and low resolution agreement — the case that motivates the metric.

## 7. Validation and reporting integration

- [ ] 7.1 Mark runs against `reconstructed` manifests as diagnostic-only in `backtest/` reporting.
- [ ] 7.2 Report a *passing* diagnostic-only result with an explicit "requires captured-BRTI validation" status; report a *failing* result as directly actionable.
- [ ] 7.3 Ensure a diagnostic-only run cannot record a satisfied promotion criterion in `backtest/promotion_gate.py`.
- [ ] 7.4 Add a reconstruction-error threshold to `data/quality_policy.py` with a bumped policy version; leave the admission threshold itself unset pending first measurement (design Open Questions).
- [ ] 7.5 Add tests covering the reject-but-never-admit asymmetry end to end.

## 8. Operator commands and dashboard

- [ ] 8.1 Add `scripts/backfill_constituents.py`: bounded, foreground download/verify/normalize for a named venue, asset, and window.
- [ ] 8.2 Add `scripts/compose_synthetic_brti.py`: bounded composition over a window, printing contributor coverage.
- [ ] 8.3 Add `scripts/reconstruction_report.py`: print level error, resolution agreement, or `unmeasured`.
- [ ] 8.4 Extend dashboard data/coverage views to separate source-native from reconstructed coverage and to surface `unmeasured` explicitly.
- [ ] 8.5 Surface the `reconstructed_data_not_admissible` preflight reason in the paper-run views, so a blocked fill is legible to an operator.

## 9. Documentation and verification

- [ ] 9.1 Document in the change notes why TradingView cannot serve this purpose — paid-plan export, 40,000-bar ceiling (≈28 days at 1-minute), no programmatic API — so the question is not re-litigated.
- [ ] 9.2 Document the constituent list, its source, and the fact that constituent membership can drift over history.
- [ ] 9.3 Document the reject-but-never-admit rule and its rationale in the data-source docs.
- [ ] 9.4 Run `uv run pytest` and `uv run ruff check`; confirm the full suite passes.
- [ ] 9.5 Verify against real acquisition: fetch one bounded Kraken window, compose it, and confirm the report reads `unmeasured` while no BRTI capture exists — the expected honest result at this stage.
