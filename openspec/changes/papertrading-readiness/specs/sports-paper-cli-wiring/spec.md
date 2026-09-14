# Sports paper CLI wiring

## ADDED Requirements

### Requirement: `run_paper.py` constructs a sports adapter

`scripts/run_paper.py`'s `_build_adapter` SHALL construct a
`SportsPaperAdapter` when invoked with `--domain sports`, instead of raising
`SystemExit`. This requirement governs CLI wiring only; it SHALL NOT alter
`evaluate_sports_paper_admission`'s refusal conditions.

#### Scenario: Sports domain no longer exits immediately
- **WHEN** `run_paper.py` is invoked with `--domain sports`
- **THEN** `_build_adapter` returns a `SportsPaperAdapter` instance
- **AND** no `SystemExit` is raised for an unrecognized domain

#### Scenario: Sports still refuses fills without a promising feasibility report
- **WHEN** a sports paper run executes a tick with no feasibility report at
  `research_promising`
- **THEN** the run records a refusal via `evaluate_sports_paper_admission`
- **AND** no fill is produced
