# Research handoff

Current milestone: **paper-forward LIVE** for the FINAL-001 arms (started 2026-08-24,
journal `reports/artifacts/altcoin-carry-final-001/forward/`, runner
`research/altcoin_carry_forward.py --run` daily; SAFE = SELECT config, RISK = SL-001
arm, mode-tagged; strict no-backfill — sealed reserve 2026-07…08 never evaluated).
SELECT daily-return series exported for portfolio analysis with the external D6 line:
`reports/artifacts/altcoin-carry-final-001/select-daily-returns.{csv,json}`.
Price-only MR line CLOSED (`NO_SELECTION` accepted, `ALTCOIN_MR_TF_001_HANDOFF.md`).

Prior milestones: **ALTCOIN_CARRY_FINAL_001 — `SELECT`** (first of the program):
hardened carry, net +763% / Sharpe 1.44 / DD −20.9% over 2021–2026-06, all gates passed
(freeze `240598a`, engine `research/altcoin_carry_final_001.py`). **ALTCOIN_MR_TF_001 —
`NO_SELECTION`**: gross intraday bounce unsignifiable, shorts toxic, daily MR flat
(freeze `db6e4f8`). TIDAL SAFE-mode candidate = SELECT config; RISK mode = SL-001 RISK arm.

Reporting convention for any assistant/human finishing a protocol:
`docs/RESEARCH_REPORTING_STANDARD.md`.

Hypothesis queue: H-XS (cross-sectional momentum), H-VOL (volatility-regime
conditioning), portfolio day-brake, cooldown variants, TF pack 2 (blocked: needs a new
information set). External line (DO NOT touch from this repo): D6 cascade reversion in
`SMC-Research-Engine` — owner resolves the population question before TIDAL integration.

History: trend family closed by 007; CARRY-001 found the premium; RM-001 showed overlays
whipsaw; SL-001 showed takes (not stops) fix drawdowns; FINAL-001 hardened past every
gate; MR-TF-001 closed the price-only reversion line. Program rules unchanged: freeze
before analysis, gates never weakened, heritage multiplicity pricing (N ≥ 6,122).
Monitor reserve 2026-07…08 sealed.
