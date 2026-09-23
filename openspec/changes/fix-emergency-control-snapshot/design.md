## Context

`DailyLossGuard.allows_new_entries()` requires an as-of `datetime` because it rolls its UTC-day state before returning. `EmergencyControl.snapshot()` currently cannot perform that evaluation: it holds the bound method, which is truthy, and accepts no timestamp. This leaves a daily-loss-only breach invisible in a no-panel snapshot.

## Goals / Non-Goals

**Goals:**

- Make snapshot observation timestamp-aware and use the same daily-loss semantics as entry admission.
- Prove that a daily-loss-only breach halts a snapshot without a dashboard panel.
- Prove snapshot evaluates day rollover using its supplied timestamp.

**Non-Goals:**

- Changing loss thresholds, reset policy, `ControlPanel`, global governance, execution authority, or scanner behavior.

## Decisions

Require `snapshot(ts: datetime)` rather than using wall-clock time. Its contract becomes explicit, replayable, and compatible with `DailyLossGuard`. It delegates halted determination to `not allows_new_entries(ts)`: only the daily-loss guard consumes the timestamp, while the existing control-panel short circuit and other guards retain their current semantics. The paper runner's suppressed-signal log passes its existing cycle timestamp.

Alternative: use `datetime.now()` internally. Rejected because it makes historical/replay state nondeterministic and uses a time source different from the caller's decision time. Alternative: alter `DailyLossGuard` to accept no timestamp. Rejected because its UTC rollover contract is already correct and used by the entry gate.

## Risks / Trade-offs

- [Existing callers omit a timestamp] → type checking and focused tests reveal the required call-site update; no current production caller was found before the change.
- [Snapshot incorrectly reports a new day] → use a targeted rollover test with UTC timestamps.
- [Safety behavior changes outside daily loss] → preserve and regression-test drawdown, consecutive-loss, and panel behavior.

## Migration Plan

1. Change the snapshot signature and call the daily-loss guard with its timestamp.
2. Add focused no-panel and rollover regression tests.
3. Run the emergency-control tests and the full suite before recording this independent change as complete.

Rollback restores the prior source only if the replacement tests show a compatibility failure; no storage or external migration is involved.

## Open Questions

None. The required time source and guard behavior are established by the existing `allows_new_entries(ts)` contract.

## Model complexity

The code patch is small but affects fail-closed risk visibility. GPT-6 Astra owns design and final safety review; GPT-5.6 Sol/Terra can implement and verify the bounded edit. GPT-5.6 Luna may assist only with fixed test data. Escalate timestamp, guard-order, or caller-compatibility uncertainty to Astra; no reduced test standard is acceptable.
