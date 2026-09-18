# Sports feasibility pilot pre-registration

Complete this file before examining the holdout. Blank values make a run
`insufficient_data`, never a promotion.

- Sport / series: `KXNFLGAME` (NFL, two-outcome game moneyline)
  - Chosen 2026-09-13 via a live discovery pass (`scripts/capture_sports.py
    --series KXNFLGAME,KXNBAGAME,KXNHLGAME,KXMLBGAME,KXNCAAFGAME,KXNCAABGAME
    --discover --report`) per design D1 (liquidity-driven, not popularity-driven).
    NFL had 81 distinct events / 162 markets live at capture time, avg open
    interest ~1.14M and avg volume ~2.39M per discovery row — comparable to or
    ahead of every other in-season two-outcome series checked, with a much
    cleaner one-game-per-market shape than NCAAF (570 events, more thin-book
    games mixed in) or MLB (970 events, largest series but per-game liquidity
    diluted by game count). NBA/NCAAB were excluded: regular season had not
    started yet (2026-09-13), so only a handful of markets existed.
- Supported shape: two-outcome, single-game only
- Discovery thresholds: min open interest `TBD`; min top-of-book depth `TBD`; max spread cents `TBD`
- Holdout boundary (UTC epoch): `TBD`
- Fee schedule source/version: `TBD`
- Slippage assumption (cents): `TBD`
- Minimum holdout observations: `TBD`
- Minimum confidence threshold: `TBD`
- Candidate signal and features available by: `TBD`
- External provider: none unless separately approved adapter is configured

The completed values and timestamp of this file are part of the validation
run provenance. No paper or live orders are enabled by this research.
