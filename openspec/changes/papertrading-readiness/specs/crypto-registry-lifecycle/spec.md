# Crypto registry lifecycle

## ADDED Requirements

### Requirement: Registry lifecycle vocabulary includes `shadow`

`CryptoInstrumentConfig.lifecycle` SHALL accept `"shadow"` as a valid value,
matching `LifecycleState`'s vocabulary in `config/lifecycle.py`.
`validate_registry` SHALL accept a registry containing a `shadow`-lifecycle
instrument without raising.

#### Scenario: A shadow-lifecycle instrument constructs and validates
- **WHEN** a `CryptoInstrumentConfig` is constructed with `lifecycle="shadow"`
- **THEN** construction succeeds
- **AND** `validate_registry` on a registry containing it does not raise

#### Scenario: An unsupported lifecycle value is still rejected
- **WHEN** a `CryptoInstrumentConfig` is constructed with an unsupported
  lifecycle value
- **THEN** construction raises a validation error

### Requirement: At least one series is promoted to shadow

`DEFAULT_CRYPTO_REGISTRY` SHALL contain at least one event instrument at
`lifecycle="shadow"`, so that `run_preflight` admits it to shadow-mode
decision recording under the strategy lab without further configuration
changes.

#### Scenario: A shadow-promoted series is admitted to shadow-mode decisions
- **WHEN** a paper run targets the promoted series in shadow mode
- **THEN** `run_preflight` does not refuse it on lifecycle grounds
- **AND** the run records decisions without producing fills
