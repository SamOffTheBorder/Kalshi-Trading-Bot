## ADDED Requirements

### Requirement: Independent perpetual strategy gate
The system SHALL evaluate perpetual-futures strategies in a separate ledger and promotion report from binary-event strategies. The report SHALL include entry and exit fees, funding, margin or liquidation exposure, and residual hedge risk where applicable.

#### Scenario: Event strategy passes but perp strategy has no evidence
- **WHEN** a binary-event strategy satisfies its paper-trading gate and the related perpetual strategy has not passed its own gate
- **THEN** the system keeps the perpetual strategy disabled

### Requirement: Compatible funding hedge evidence
The system SHALL not label a funding-carry position market neutral when its hedge has a discontinuous binary payoff against a linear perpetual exposure. A funding-carry candidate SHALL demonstrate a compatible linear hedge, its rebalance cadence, complete fees, and residual basis risk before it can be evaluated for promotion.

#### Scenario: Binary hedge proposed for linear perpetual exposure
- **WHEN** a funding-carry configuration pairs a linear perpetual position with binary event contracts as its only hedge
- **THEN** the system rejects the market-neutral classification and does not promote the configuration

### Requirement: Reconciled perpetual execution safety
The system SHALL reconcile submitted perpetual orders and positions after restart, handle partial fills and stale orders, use anchored reduce-only exit triggers when supported, and verify that an emergency close produced a fill before reporting the position closed.

#### Scenario: Emergency close acknowledgement without fill
- **WHEN** an emergency close request is accepted but no fill confirmation is available
- **THEN** the system reports the position as unresolved and continues reconciliation rather than marking it closed

#### Scenario: Exit trigger is submitted before entry fill
- **WHEN** the exchange supports an exit trigger anchored to the entry order and the entry has not yet filled
- **THEN** the system creates the anchored reduce-only trigger in the pending-on-entry state
