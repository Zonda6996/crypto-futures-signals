# Research handoff

Current milestone: **ALTCOIN_CARRY_RM_001 (risk-managed funding carry) executed —
verdict `NO_SELECTION`**. The drawdown overlay works as designed (4/8 configurations
now pass eligibility; max DD cut from −20% to −15…−19%) but statistical gates stay red
under program-level multiplicity pricing (best DSR 0.933 < 0.95 at N = 6,052 heritage).
Details: `ALTCOIN_CARRY_RM_001_HANDOFF.md`; protocol:
`ALTCOIN_CARRY_RM_001_FROZEN_PROTOCOL.md` (freeze proof `68482d4`); engine:
`research/altcoin_carry_rm_001.py`.

Hypothesis queue (each requires its own pre-analysis freeze):
1. H-CARRY-SL — carry with per-position stops / take-profits, partial profit-taking
   (explicitly requested by the project owner).
2. H-MR — daily mean reversion after sharp down-days.
3. H-XS — cross-sectional momentum, market-neutral.
4. H-VOL — volatility-regime conditioning.

History: ALT-MULTITF trend family closed by 007 (`NO_SELECTION`, 2021–2026‑06,
closure record `ALTCOIN_MULTITF_007_FINAL_HANDOFF.md`). CARRY-001 proved a gross
carry premium survives costs (10/11 configs net-positive) but failed deployability on
drawdowns and multiplicity. Program rules unchanged: one freeze before any window
analysis, gates never weakened, cumulative search priced via heritage DSR
(N ≥ 6,052). Monitor reserve 2026‑07…08 remains untouched.
