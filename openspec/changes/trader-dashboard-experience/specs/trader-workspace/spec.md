## ADDED Requirements

### Requirement: Persistent scoped navigation
The dashboard SHALL provide Trading Desk, Markets, Portfolio, Strategies, Operations, and Settings navigation, persistent account/domain/mode context, observed engine state, source age, alerts, and a supported halt control. Scope changes SHALL only change viewed data. Existing dashboard URLs SHALL remain reachable with equivalent context.

#### Scenario: Switch viewed account
- **WHEN** the operator changes the selected paper account and opens Portfolio
- **THEN** the selected scope is retained, all rows match it, the mode remains visible, and no execution configuration or process changes.

### Requirement: Prioritized desk and onboarding
The Trading Desk SHALL show scoped P&L, risk, available capital when recorded, active runs, attention items, positions, watchlist and recent decisions with drilldowns. A new installation SHALL show a configuration/capture/validation/paper-review journey instead of misleading zero metrics.

#### Scenario: First launch without records
- **WHEN** the database contains no runs or balances
- **THEN** the desk identifies missing data and offers the next setup step without displaying invented capital or starting capture or trading.

### Requirement: Accessible responsive visual system
The UI SHALL use consistent tokens, signed/tabular financial values, text status labels, labeled controls, visible focus, semantic tables, chart table alternatives, and keyboard-operable dialogs. It SHALL support 390px, 768px and 1440px widths and 200% zoom without page-level horizontal overflow or inaccessible essential controls. Normal text SHALL meet 4.5:1 contrast and large text/meaningful controls 3:1 in shipped presets.

#### Scenario: Small screen keyboard review
- **WHEN** an operator views the desk at 390px or 200% zoom and navigates using a keyboard
- **THEN** mode, state and halt remain reachable, wide tables scroll within labeled regions, and focused controls are visible.

### Requirement: Durable display preferences
The system SHALL persist theme, density, timezone, supported table columns and watchlists for the local profile, validate stored values, preserve compatible existing themes, and offer reset. Preferences SHALL NOT contain execution authorization.

#### Scenario: Preference survives restart
- **WHEN** the operator saves compact density and a timezone then reopens the dashboard
- **THEN** those display preferences are restored and no engine is armed or launched.

### Requirement: Honest incremental refresh
Refreshing panels SHALL display source and last-fetch timestamps and stale/unknown/partial states, retain last good data on failure, discard older snapshots, prevent overlapping requests, and preserve focus/forms. Status polling SHALL target 5 seconds and show disconnected after two failed intervals; source staleness SHALL use source-specific cadence. Hidden tabs SHALL pause polling and refetch on focus.

#### Scenario: Refresh failure
- **WHEN** two successive status refreshes fail
- **THEN** a disconnected indicator and last-successful age appear, existing values are marked outdated, and action forms are not resubmitted or replaced.

### Requirement: Local launch and bounded reads
The dashboard SHALL preserve single-action batch launch with no launch-time JavaScript build, asset CDN, or package install. GET requests SHALL NOT start trading. Lists SHALL be paginated with a maximum of 200 rows per page. The documented fixture benchmark SHALL meet the design's 2-second usable desk and 500ms p95 read-response targets.

#### Scenario: Large local history
- **WHEN** the documented 100k-decision, 10k-fill, 1k-market fixture is opened through the launcher
- **THEN** pages use bounded queries, assets load locally, benchmark results meet the targets on the recorded machine, and no trading process starts.

## Model complexity

High-complexity cross-capability contract. Follow the model allocation and escalation rules in `../../design.md`: GPT-6 Astra for requirements and control/accounting review; Claude Opus 5 is an advisory user-selected alternative. Bounded presentation work can use the documented lighter allocation only after contracts are fixed. Revisit when data coverage or execution dependencies change.

