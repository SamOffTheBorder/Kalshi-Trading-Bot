# Resumable checkpoint

- Change: `trader-dashboard-experience`.
- Stage: task 1a.1 complete; task 1a.2 is next.
- Completed: proposal, detailed design, four capability specs, tasks 1.1-1.4 and 1a.1. The task list contains 52 tasks; 5 are complete.
- Verification: `openspec validate trader-dashboard-experience`, focused dashboard/auth tests, and the full suite passed on 2026-09-14: 1003 passed, 3 deselected, 1 pre-existing third-party deprecation warning. Ruff and `git diff --check` passed.
- Review basis: source audit plus authentication implementation tests; no trading/capture process was launched.
- Current model allocation: use the strongest available model for controls and ledger work. Authentication is complete.
- Next action: `$openspec-apply-change trader-dashboard-experience`, starting task 1a.2.
- Before resuming: run `openspec status --change trader-dashboard-experience --json`; obtain applicable CLI instructions; read `proposal.md`, `design.md`, all four `specs/*/spec.md`, and `tasks.md` before making changes.
- Unresolved implementation evidence: order-book depth coverage remains deferred to task 6.4; halt propagation and per-domain ledger coverage require implementation verification.
- Model-switch trigger: selected model unavailable/context limit; preserve artifacts and completed checkboxes. Escalate from a lighter implementation model on ambiguous ledger units/IDs, execution-path changes or two repeated integration-scenario failures. Never restart completed artifacts solely because a model changed.
- Workspace contained unrelated modifications to `start_capture.bat` and untracked `scripts/series_is_current.py` before this work; they were not edited.
