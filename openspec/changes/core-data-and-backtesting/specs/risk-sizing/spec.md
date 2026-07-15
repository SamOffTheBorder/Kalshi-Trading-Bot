# risk-sizing

## ADDED Requirements

### Requirement: Fractional Kelly with hard cap
Position size SHALL be computed as `kelly_fraction × ((p − c) / (1 − c))` of broker bankroll for a binary contract at price `c` with estimated win probability `p`, then clamped by `min()` against `max_position_pct` of bankroll. The clamp MUST apply regardless of Kelly output and MUST NOT be bypassable by configuration.

#### Scenario: Kelly output exceeds cap
- **WHEN** the Kelly formula suggests 12% of bankroll and `max_position_pct` is 5%
- **THEN** the sized position is 5% of bankroll

#### Scenario: Zero or negative edge
- **WHEN** estimated probability is at or below the fee-adjusted contract price
- **THEN** the sized position is zero contracts

### Requirement: Drawdown guard state machine
The system SHALL track per-broker peak equity and current drawdown, transitioning NORMAL → PAUSED (no new entries) at `max_drawdown_pause_pct` and PAUSED → HALTED at `max_drawdown_halt_pct`. All thresholds come from `Settings` — no other definition of these values may exist anywhere in code or docs.

#### Scenario: Pause blocks new entries only
- **WHEN** drawdown crosses the pause threshold
- **THEN** new entries are blocked while existing positions remain open

#### Scenario: Halt threshold reached
- **WHEN** drawdown crosses the halt threshold
- **THEN** the guard reports HALTED state (close-all wiring arrives with execution changes)

### Requirement: Sizing works identically in backtest mode
The same sizing and guard code SHALL be invoked by the backtest engine, so backtest results reflect the risk limits that will govern live trading.

#### Scenario: Backtest respects the cap
- **WHEN** a backtest run processes a high-edge opportunity
- **THEN** the simulated position size shows the same 5% clamp as live sizing would
