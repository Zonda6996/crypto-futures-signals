# Research handoff

Current milestone: **ALTCOIN_CARRY_FINAL_001 — `SELECT`** (first of the program).
Hardened carry: core A + atr3 stop + full-take-1R + BTC beta-hedge + inverse-vol
weights. Net +763% over 2021–2026-06 (~+48%/yr), Sharpe 1.44, maxDD −20.9%, 9/11
positive half-years, ALL frozen gates passed (SPA 0.025, DSR 1.000, Holm 0.024,
bootstrap CI-low > 0, stress ×4, neighbours). Heritage DSR 0.019 at N = 6,090
(report-only). This is the LAST in-sample pass; next validation is forward-only on the
untouched reserve 2026-07…08. Details: `ALTCOIN_CARRY_FINAL_001_HANDOFF.md`; protocol:
`ALTCOIN_CARRY_FINAL_001_FROZEN_PROTOCOL.md` (freeze proof `240598a`); engine:
`research/altcoin_carry_final_001.py`. TIDAL SAFE-mode candidate = selected config;
RISK mode = SL-001 RISK arm (pending forward).

Reporting convention for any assistant/human finishing a protocol:
`docs/RESEARCH_REPORTING_STANDARD.md`.

Hypothesis queue: H-MR (daily mean reversion), H-XS (cross-sectional momentum),
H-VOL (volatility-regime conditioning), portfolio day-brake, cooldown variants.
External line (DO NOT touch from this repo): D6 cascade reversion (OI-flush, leverage
flow) lives in `SMC-Research-Engine` — two GO replications on symbol-fresh listings,
non-replication on old listings, paper-forward running. Owner resolves population
question before any integration into the TIDAL product.

History: trend family closed by 007; CARRY-001 found the premium; RM-001 showed
portfolio overlays whipsaw; SL-001 showed takes (not stops) fix drawdowns and found the
base champion; FINAL-001 hardened it past every gate. Program rules unchanged: freeze
before analysis, gates never weakened, heritage multiplicity pricing (N ≥ 6,090).
Monitor reserve 2026-07…08 untouched.
