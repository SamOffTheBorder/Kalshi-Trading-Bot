## 1. Registry lifecycle: unblock `shadow`

- [x] 1.1 Add `"shadow"` to `CryptoInstrumentConfig`'s `LifecycleMode` literal
      in `config/crypto_registry.py`, matching `config/lifecycle.py`'s
      `LifecycleState`.
- [x] 1.2 Update `validate_registry`'s inline allowed-lifecycle set
      (`config/crypto_registry.py`) to accept `"shadow"`.
- [x] 1.3 Add a regression test asserting a registry row with
      `lifecycle="shadow"` constructs and validates without error, and that
      an unsupported value (e.g. `"live-ish"`) still raises.
- [x] 1.4 Promote BTC 15m's `lifecycle` from `"backtest"` to `"shadow"` in
      `DEFAULT_CRYPTO_REGISTRY`, as the deliberate operator decision recorded
      in this change (see proposal Open Question 1). Leave BTC 60m, ETH,
      SOL, XRP unchanged.
- [x] 1.5 Run the existing `run_preflight` / registry test suite and confirm
      a BTC 15m paper run now produces `shadow`-mode decisions instead of a
      lifecycle refusal, with fills still refused pending 2.x.

## 2. Manifest freezing operator flow

- [x] 2.1 Write `scripts/freeze_manifest.py`: given `--asset`, `--source`
      (repeatable), and a time range (default: full span of captured data
      for that asset/source), query the relevant capture tables, build a
      `ManifestSpec` with honestly computed `start_ts`/`end_ts`,
      `partition_provenance`, and `coverage_summary`, and call
      `persist_manifest`.
- [x] 2.2 Populate `parser_version`/`feature_version`/`code_revision`/
      `config_sha256` from existing project version constants (reuse
      whatever `brti-constituent-history`'s reconstruction pipeline already
      uses for these fields, for consistency — do not invent a second
      versioning scheme).
- [x] 2.3 Print a JSON report (report file support via `--output`, matching
      `discover_crypto_series.py`'s pattern) showing the resulting manifest's
      `provenance_class` and whether it is `source_native`.
- [x] 2.4 Add a unit test: freezing from a fixture with only source-native
      partitions yields a `source_native` manifest; freezing from a fixture
      with a reconstructed partition yields a non-`source_native` manifest
      and the script still exits 0 (freezing is not a fill-eligibility
      claim).
- [x] 2.5 Run the script for BTC (15m) against currently captured
      `SpotCandle`/`BRTIObservation` data and confirm a `DatasetManifest` row
      is persisted. Record in the run's report output whether it classified
      as `source_native` (informational — do not alter capture data to force
      this).

## 3. Perp discovery pass

- [x] 3.1 Write `scripts/discover_crypto_perps.py`, mirroring
      `scripts/discover_crypto_series.py`: iterate `DEFAULT_CRYPTO_REGISTRY`
      assets with a non-`None` `.perp`, call `PerpDiscovery(client).refresh`,
      print/optionally-write a JSON report of eligibility and failure
      reasons per asset.
- [x] 3.2 Add a unit test using a fake client (matching the existing
      `PerpDiscovery` test fixtures) confirming the script persists one
      `DiscoveryResult` row per registry perp asset and reports eligibility
      correctly.
- [x] 3.3 Run the script against the live registry (foreground, respecting
      `KalshiPublicClient`'s rate limiter) and confirm `DiscoveryResult` rows
      with `instrument="perp"` now exist for BTC/ETH/SOL/XRP.
- [x] 3.4 Confirm `evaluate_perp_admission` no longer returns
      `no_discovery_snapshot` for an asset with a fresh snapshot, and still
      correctly returns a marks-staleness refusal separately (marks are a
      distinct, second gate — this task does not re-capture marks).

## 4. Sports paper CLI wiring

- [x] 4.1 Extend `scripts/run_paper.py:_build_adapter` with a `domain ==
      "sports"` branch constructing `SportsPaperAdapter`, matching the
      existing prediction/perp branches' session-factory/settings/run-id
      wiring.
- [x] 4.2 Add a unit test invoking `_build_adapter("sports", ...)` and
      asserting it returns a `SportsPaperAdapter` instance rather than
      raising `SystemExit`.
- [x] 4.3 Add an integration-style test running one tick of
      `--domain sports` end to end against a DB with no feasibility report,
      confirming it records a refusal (`research_not_promising` or
      equivalent) rather than crashing or silently permitting a fill.
- [x] 4.4 Update `docs/paper-operations.md`'s domain list to mention sports
      is CLI-wired but gated on its feasibility report, cross-referencing
      `sports-market-feasibility` and `sports-evidence-and-flow-research`.

## 5. Readiness matrix

- [x] 5.1 Extend `web/queries.py` with a `papertrading_readiness()` query
      returning, per domain (prediction/perp/sports) and asset: registry
      lifecycle, manifest-frozen boolean + provenance class, discovery
      snapshot presence + freshness, mark/BRTI freshness, and (sports only)
      feasibility-report outcome.
- [x] 5.2 Add a dashboard section (new template section or extend
      `market_area.html`'s existing "Per-asset admission" panel) rendering
      this matrix, following the existing badge conventions
      (`badge-ok`/`badge-warn`/`badge-info`).
- [x] 5.3 Add a `test_dashboard_*` test asserting the matrix reflects a
      known DB fixture's state (lifecycle promoted, manifest present, perp
      discovery present, sports report absent) correctly.
- [x] 5.4 Manually verify the rendered page against the live dev DB after
      tasks 1–4 have run, confirming BTC 15m shows `shadow` + manifest
      present, perp assets show discovery present + marks stale, and sports
      shows CLI-wired + report absent.

## 6. Documentation and verification

- [x] 6.1 Update `docs/paper-operations.md` with the new
      `freeze_manifest.py` and `discover_crypto_perps.py` entrypoints under
      "Data storage and sources" / "Strategy lab" as appropriate.
- [x] 6.2 Run the full unit test suite and ruff on all changed/new files.
- [x] 6.3 Run one live shadow-mode tick of `scripts/run_paper.py --domain
      prediction --strategy trend_scalp --asset BTC` (or the appropriate
      registry-selected strategy) and confirm the audit trail shows a
      `shadow`-lifecycle decision, not a lifecycle refusal.
- [x] 6.4 Update this change's own `proposal.md`/`design.md` if any task
      above surfaces a finding that changes the recommended defaults (e.g.
      BTC 15m's manifest freezes as non-`source_native` and a different
      series is a better shadow candidate).
