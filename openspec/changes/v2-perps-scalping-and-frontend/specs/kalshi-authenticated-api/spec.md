# kalshi-authenticated-api

## ADDED Requirements

### Requirement: RSA-PSS request signing
The client SHALL sign every authenticated request using the RSA private key at `kalshi_private_key_path`, producing the signature over the concatenation of timestamp, HTTP method, and request path, and SHALL send the key ID and signature in the required headers.

#### Scenario: Signed request accepted by demo environment
- **WHEN** a read-only authenticated request is made against the demo environment with a valid key
- **THEN** the response is HTTP 200 and contains the account's data

#### Scenario: Missing key fails loudly
- **WHEN** an authenticated call is attempted with no key ID or no private key file present
- **THEN** the client raises a configuration error before issuing any network request

### Requirement: Demo and production environments are structurally distinct
The client SHALL select its base URL from `kalshi_use_demo_env` and SHALL refuse to place orders against production while `paper_trading` is true.

#### Scenario: Production order blocked in paper mode
- **WHEN** an order placement is attempted with `kalshi_use_demo_env=false` and `paper_trading=true`
- **THEN** the client raises an error and no network request is made

### Requirement: Read-only account access
The client SHALL expose balance, positions, fills, and order history for both event contracts and margin accounts.

#### Scenario: Fills retrieved
- **WHEN** fills are requested for a date range
- **THEN** each fill includes ticker, side, quantity, price, fee, and timestamp

### Requirement: Exit-trigger (bracket) management
The client SHALL support attaching stop-loss and take-profit brackets and trailing stops to margin positions via the exchange's exit-trigger endpoints, and SHALL support cancelling them by ID.

#### Scenario: Bracket attached at entry
- **WHEN** a margin position is opened with a configured stop and target
- **THEN** the corresponding exit triggers exist server-side and are returned by a subsequent query

### Requirement: Maker-preferred order placement
Order placement SHALL default to resting limit orders rather than marketable orders, because maker fees are approximately one quarter of taker fees.

#### Scenario: Default order is a resting limit
- **WHEN** an order is placed without an explicit execution-style override
- **THEN** the submitted order is a limit order priced to rest rather than to cross
