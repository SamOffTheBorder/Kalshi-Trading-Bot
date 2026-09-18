# operator-dashboard

## ADDED Requirements

### Requirement: Single-action launch with no build step
The dashboard SHALL start from one batch file that launches the server and opens a browser, with no JavaScript build step or package installation required at launch time.

#### Scenario: Batch file launch
- **WHEN** the user runs the dashboard batch file
- **THEN** the server starts and a browser opens to the dashboard

### Requirement: Trading starts stopped
Launching the dashboard SHALL NOT start trading. Trading SHALL begin only after an explicit operator action in the UI.

#### Scenario: Dashboard opened for monitoring only
- **WHEN** the dashboard is launched
- **THEN** no orders are placed until the operator activates trading

### Requirement: Kill switch always reachable
A halt control SHALL be present on every dashboard view and SHALL stop new entries and trigger the emergency-control path in one action.

#### Scenario: Halt from any view
- **WHEN** the operator activates the kill switch from any page
- **THEN** new entries stop immediately and the halt is recorded

### Requirement: Decisions including HOLDs are visible
The dashboard SHALL display recent decisions including HOLD decisions and their reasons, not only executed trades.

#### Scenario: HOLD reasons shown
- **WHEN** a strategy declines to trade
- **THEN** the decision and its reason appear in the dashboard's recent-decision view

### Requirement: Risk state is visible at a glance
The dashboard SHALL display open positions with unrealized PnL, guard state, daily PnL against the loss limit, and, for leveraged positions, distance to liquidation and next funding time.

#### Scenario: Leveraged position risk shown
- **WHEN** a perps position is open
- **THEN** its liquidation distance and next funding payment are displayed

### Requirement: Not exposed beyond loopback without a secret
The server SHALL bind to loopback by default, and SHALL refuse to bind to a non-loopback interface unless an authentication secret is configured.

#### Scenario: Non-loopback bind without secret
- **WHEN** the server is configured to bind beyond loopback with no auth secret set
- **THEN** startup fails with a configuration error
