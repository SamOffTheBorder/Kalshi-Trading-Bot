# Sports feasibility runbook

This change is research-only. It never places paper or live sports orders.

1. Before looking at holdout data, pre-register the sport/series, discovery
   thresholds, holdout boundary, fee/slippage assumptions, and minimum sample
   and confidence gates in `docs/sports-feasibility-preregistration.md`.
2. Review each series' current rules and settlement source. Only two-outcome,
   single-game markets with a current two-sided quote and minimum displayed
   depth are supported. Futures, props, parlays/combos, multi-outcome markets,
   and unknown rules are rejected.
3. Run the foreground command manually. For example:

   `uv run python scripts/capture_sports.py --series KXNBAGAME --discover`

   Then capture a bounded interval with `--capture --start-ts ... --end-ts ...`.
   The command exits after the requested work; no scheduler or restart loop is
   installed. Repeat cadence manually and inspect `--report` for gaps.
4. Never interpolate missing candles, books, trades, scores, lineups, or
   external observations. Rule changes create a new provenance snapshot.
5. Run validation only after the pre-registered chronological holdout is
   complete. A `research_promising` result requires a separate, future paper
   trading proposal; it does not authorize execution.
