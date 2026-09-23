## 1. Timestamp-aware snapshot correction

- [x] 1.1 Review the `DailyLossGuard` timestamp and UTC-rollover contract against `EmergencyControl.allows_new_entries`; preserve all other guard semantics. (2026-09-23: `DailyLossGuard` rolls at supplied UTC time; snapshot delegates to the same admission predicate, retaining panel short-circuit and other guard order.)
- [x] 1.2 Change `EmergencyControl.snapshot` to require an observation timestamp and invoke the daily-loss guard at that timestamp. (2026-09-23: required `ts` added; paper runner's one production call passes its cycle `now_dt`.)

## 2. Regression coverage and acceptance

- [x] 2.1 Add a daily-loss-only/no-control-panel snapshot regression test and UTC-rollover test. (2026-09-23: added no-panel daily-loss/reason, no-panel rollover, and panel-sticky-after-rollover tests; focused emergency-control plus paper-runner tests pass: 15 passed.)
- [ ] 2.2 Run focused emergency-control tests and the default test suite; record results and verify no caller still omits the snapshot timestamp.
- [ ] 2.3 Run strict OpenSpec validation and record the independent commit/PR evidence needed by `polymarket-us-and-sports-scanner` task 1.2.

## 3. Model and handoff

- [ ] 3.1 Record GPT-6 Astra safety review, bounded implementation allocation, verification evidence, and the scanner prerequisite handoff without claiming an unavailable model executed work.
