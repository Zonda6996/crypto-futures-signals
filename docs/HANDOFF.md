# Research handoff

Current milestone: **ALTCOIN_XS_001 — `NO_SELECTION`** (cross-sectional momentum,
12 configs, 0 eligible, family closed). Daily-rebalanced momentum is suicide
(−95…−98%); the only decent arm (14d window, weekly, K=2: +485%, Sharpe 1.01,
SPA 0.026) fails eligibility on DD −43.6% and is mostly market beta (B&H basket
+583%). Details: `ALTCOIN_XS_001_HANDOFF.md`; protocol
`ALTCOIN_XS_001_FROZEN_PROTOCOL.md` (freeze proof `8635b73`); engine
`research/altcoin_xs_001.py`.

Also live: **paper-forward** for the FINAL-001 arms (journal
`reports/artifacts/altcoin-carry-final-001/forward/`, report.md auto-generated;
run `research.altcoin_carry_forward --run` daily). Price-only MR line CLOSED
(`ALTCOIN_MR_TF_001_HANDOFF.md`).

Prior milestone: **ALTCOIN_CARRY_FINAL_001 — `SELECT`** (first of the program):
hardened carry, net +763% / Sharpe 1.44 / DD −20.9% over 2021–2026-06, all gates
passed (freeze `240598a`, engine `research/altcoin_carry_final_001.py`).
TIDAL SAFE-mode candidate = SELECT config; RISK mode = SL-001 RISK arm.

Reporting convention for any assistant/human finishing a protocol:
`docs/RESEARCH_REPORTING_STANDARD.md`.

Hypothesis queue (all low-priority): H-VOL, day-brake, cooldowns, atr3+flip combo.
Blocked: TF pack 2 (needs new information set); maker (owner decision); carry
in-sample re-tune (FINAL-001 declared it concluded). External line (DO NOT touch):
D6 cascade in `SMC-Research-Engine` — population resolved (control replicated
+3.11%), multi-TF GOs on 5m/15m, D6×TIDAL portfolio feasibility corr 0.084;
integration is a joint decision with the owner.

History: trend family closed by 007; CARRY-001 found the premium; RM-001 showed
overlays whipsaw; SL-001 showed takes fix drawdowns; FINAL-001 hardened past every
gate (SELECT); MR-TF-001 closed price-only reversion; XS-001 closed cross-sectional
momentum. Program rules unchanged: freeze before analysis, gates never weakened,
heritage multiplicity pricing (N ≥ 6,134). Monitor reserve 2026-07…08 sealed.
