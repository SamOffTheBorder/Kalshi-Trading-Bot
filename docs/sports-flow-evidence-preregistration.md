# Sports flow/evidence pilot preregistration

This is the operator contract for the first anonymous-flow and evidence pilot.
It must be filled before the holdout boundary is opened; changing a field
creates a new version rather than editing the prior record.

```yaml
pilot_version: sports-flow-evidence-pilot-v1
series_tickers: []
market_tickers: []
evidence_allowlist:
  providers: []
  domains: []
holdout_boundary_ts: null
flow_window_seconds: 300
response_horizon_seconds: 60
minimum_training_samples: 30
minimum_holdout_samples: 100
edge_threshold: 0.0
slippage_cents: 0.0
required_variants: [market-baseline, flow-only, evidence-only, combined]
execution_enabled: false
```

The pilot records feature versions and hashes, source-card hashes, model and
prompt/output hashes, calibration, executable fills, concentration, drawdown,
and the final `research_promising`, `park`, or `insufficient_data` outcome.
Anonymous Kalshi flow is the only default input. Named-trader copying remains
`copy_trading_unsupported`, and no scheduler or order API is permitted.
