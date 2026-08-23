# Research handoff

Current milestone: **ALTCOIN_CARRY_SL_001 (carry with stops & takes) executed —
verdict `NO_SELECTION`**. Episode engine with ATR stops / funding-flip / take-family.
One configuration (A + atr3 + full-take-1R: +884%, Sharpe 1.25, DD −23.0%) passes
eligibility, SPA and DSR but fails Holm (0.092 > 0.05); heritage DSR at N = 6,082 is
0.0014. Key finding: price stops cannot fix gap-day drawdowns; tight take-profits can.
Details: `ALTCOIN_CARRY_SL_001_HANDOFF.md`; protocol:
`ALTCOIN_CARRY_SL_001_FROZEN_PROTOCOL.md` (freeze proof `afb3794`).

Reporting convention for any assistant/human finishing a protocol:
`docs/RESEARCH_REPORTING_STANDARD.md`.

Hypothesis queue: H-MR (daily mean reversion), H-XS (cross-sectional momentum),
H-VOL (volatility-regime conditioning), portfolio day-brake, cooldown variants.

History: trend family closed by 007; CARRY-001 found the gross premium (10/11 net-positive);
RM-001 proved a drawdown overlay works mechanically but whipsaws; SL-001 showed tight
take-profits — not stops — are the tool that lands inside the risk ceiling. Program
rules unchanged: freeze before analysis, gates never weakened, heritage multiplicity
pricing (N ≥ 6,082). Monitor reserve 2026‑07…08 untouched.
