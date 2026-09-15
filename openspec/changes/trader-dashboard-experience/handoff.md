# Resumable checkpoint

- Change: `trader-dashboard-experience`.
- Stage: planning complete; ready to apply, implementation not started.
- Completed: proposal, detailed design, four capability specs (22 requirements/scenarios), 50 implementation tasks.
- Verification: `openspec validate trader-dashboard-experience` passed on 2026-09-14; JSON status reports all four planning artifact IDs done and `isComplete: true`.
- Review basis: repository source audit; no runtime visual verification, application changes or trading/capture launches performed.
- Current/recommended planning model: GPT-6 Astra. Follow design model matrix; Anthropic allocations advisory only.
- Next action: `$openspec-apply-change trader-dashboard-experience`, starting task 1.1.
- Before resuming: run `openspec status --change trader-dashboard-experience --json`; obtain applicable CLI instructions; read `proposal.md`, `design.md`, all four `specs/*/spec.md`, and `tasks.md` before making changes.
- Unresolved implementation evidence: per-domain order/mark/balance coverage, halt propagation to all managed runners, related-change ownership. Defaults and unavailable behavior are defined in design; no user decision blocks this proposal.
- Model-switch trigger: selected model unavailable/context limit; preserve artifacts and completed checkboxes. Escalate from a lighter implementation model on ambiguous ledger units/IDs, execution-path changes or two repeated integration-scenario failures. Never restart completed artifacts solely because a model changed.
- Workspace contained unrelated modifications to `start_capture.bat` and untracked `scripts/series_is_current.py` before this work; they were not edited.
