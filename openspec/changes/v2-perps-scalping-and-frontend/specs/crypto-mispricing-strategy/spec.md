# crypto-mispricing-strategy

## REMOVED Requirements

### Requirement: Composite fee-aware edge decision
**Reason**: Out-of-sample calibration testing showed the zero-drift Black-Scholes/Monte-Carlo pricer does not produce a usable directional edge on BTC. The model's 40%-confidence bucket won 20% of the time, and it claimed a +0.64 edge on a 3¢ contract. Its apparent profit came from fills against markets with no real quotes, and 122% of test-segment profit came from ten trades.

**Migration**: Replaced by the `scalping-strategies` capability, which trades with short-term trend at fixed R multiples on liquid instruments. The existing module remains in the repository for reference and for backtest comparison, but is not part of the live decision path.

### Requirement: Trend-regime gate
**Reason**: The gate was a patch that suppressed trading during trends the pricer could not handle, rather than a source of edge. Trend behavior is handled directly by the replacement strategies, which trade with trend rather than needing to detect and avoid it.

**Migration**: Superseded by the directional posture requirement in `scalping-strategies`.
