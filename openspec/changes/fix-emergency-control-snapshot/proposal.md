## Why

`EmergencyControl.snapshot()` can misreport a breached daily-loss guard when no dashboard `ControlPanel` is attached because it retains the guard method rather than invoking it with a timestamp. Scanner and dashboard safety state must not conceal that breach.

## What Changes

- Make `snapshot()` accept an explicit timestamp and evaluate `DailyLossGuard.allows_new_entries(timestamp)`.
- Add a regression test for a daily-loss-only breach without a control panel, plus timestamp/day-rollover coverage.
- Keep the change limited to safety-state observation; it does not alter entry, execution, storage, dashboard, or risk-limit policy.

## Capabilities

### New Capabilities

- `emergency-control-snapshot`: Timestamp-aware, fail-closed emergency-state reporting consistent with the composed guard contract.

### Modified Capabilities

None. There are no living capability specifications under `openspec/specs/`.

## Impact

Touches `risk/emergency_control.py`, its unit tests, and the scanner integration checkpoint. This is a small but high-safety-impact correction. GPT-6 Astra owns the contract and acceptance review; GPT-5.6 Sol/Terra may implement the bounded patch after that review, and Luna is limited to mechanical test fixtures. Escalate any ambiguity about observation timestamps, guard semantics, or callers to architecture review; do not weaken the regression requirement.
