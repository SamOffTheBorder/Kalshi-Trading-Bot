## ADDED Requirements

### Requirement: Timestamp-aware composite emergency snapshot
`EmergencyControl.snapshot` SHALL accept the caller's observation timestamp and determine halted state through the same composed admission predicate as `allows_new_entries(timestamp)`. It MUST invoke `DailyLossGuard.allows_new_entries(timestamp)` rather than treating the bound method as a boolean, while retaining the existing control-panel short circuit and drawdown/consecutive-loss semantics. A daily-loss breach SHALL make the returned `HaltState` halted even when no `ControlPanel` is attached.

#### Scenario: Daily loss breach without a control panel
- **WHEN** realized losses breach the daily-loss limit and `snapshot` is called with the same UTC day while no control panel is attached
- **THEN** the returned halt state is halted and the daily-loss guard is evaluated at the supplied timestamp

#### Scenario: Snapshot after UTC rollover
- **WHEN** a prior-day daily-loss breach is observed by `snapshot` with a timestamp in the next UTC day
- **THEN** the daily-loss guard rolls forward according to its existing policy and the snapshot does not remain halted solely from the prior-day breach

### Requirement: Safety regression coverage
The project SHALL retain focused tests for timestamp-aware daily-loss snapshots without a control panel and SHALL preserve the existing drawdown, consecutive-loss, and panel halt behavior.

#### Scenario: Guard-specific regressions run
- **WHEN** the emergency-control unit test module runs
- **THEN** daily-loss-only snapshot behavior and existing composed-guard behavior both pass
