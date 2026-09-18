# scalping-strategies

## ADDED Requirements

### Requirement: Strategies trade with short-term trend, not against it
Directional scalping strategies SHALL enter in the direction of established short-term momentum. Fading an established trend is explicitly out of scope, because the previous strategy family lost money doing exactly that.

#### Scenario: Counter-trend entry suppressed
- **WHEN** short-term momentum is established in one direction and a signal would enter against it
- **THEN** the decision is HOLD with a recorded reason

### Requirement: Deterministic level detection
Support and resistance levels SHALL be computed deterministically from price history — swing highs/lows confirmed by a configurable number of touches within a tolerance band, plus session VWAP. Identical input bars SHALL always produce identical levels.

#### Scenario: Reproducible levels
- **WHEN** the same bar series is evaluated twice
- **THEN** the detected level set is identical

### Requirement: Fixed R-multiple targets
Every entry SHALL define its risk distance `R` and its target as a multiple of `R` at decision time. A strategy SHALL NOT hold a position without a predefined stop and target.

#### Scenario: Decision carries stop and target
- **WHEN** a strategy returns an entry decision
- **THEN** the decision includes both a stop price and a target price expressed relative to entry

### Requirement: Cost floor must be cleared
A strategy SHALL NOT be enabled for live trading unless its backtested win rate exceeds the computed round-trip cost floor (spread plus fees at the traded price level) with margin.

#### Scenario: Sub-cost-floor strategy blocked
- **WHEN** a strategy's out-of-sample win rate does not exceed its cost floor
- **THEN** it remains disabled for live trading regardless of gross PnL

### Requirement: Known-answer tests for every strategy
Each strategy SHALL have unit tests driving synthetic bar sequences with hand-computed expected decisions, and SHALL reproduce them exactly.

#### Scenario: Synthetic sequence reproduces expected decisions
- **WHEN** a strategy evaluates a hand-constructed bar sequence
- **THEN** the emitted decision list matches the precomputed expected list exactly
