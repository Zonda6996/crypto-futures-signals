# ALTCOIN_CARRY_SL_001 (H-CARRY-SL "carry with stops & takes") — final handoff

Status: **protocol executed end-to-end; final verdict `NO_SELECTION`** — the single
eligible candidate (core A + atr3 stop + full take at 1R) passes SPA and DSR but fails
the Holm multiplicity gate (0.092 > 0.05). Freeze proof `afb3794`; engine
`research/altcoin_carry_sl_001.py`; episode-based holding with per-position exits.

## Inputs

Identical immutable archives; daily OHLC added for ATR(14). DECIDE window unchanged
(2021-01-01 .. 2026-06-30). Sweep runtime ~4 s for 30 configurations.

## Execution summary

| Stage | Result |
| --- | --- |
| Grid validation | exactly **30** configurations (Block 1: 8 stops, Block 2: 22 takes) |
| Eligibility | **1 of 30** passes (A + atr3 + f1:1) |
| Gates | SPA 0.038 ✓, DSR 0.997 ✓, **Holm 0.092 ✗** → `NO_SELECTION` |

## Block 1 — stop styles (take = none)

| core | stop | net | Sharpe | maxDD | folds+ | SPA | DSR | elig |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | atr3 | +940.8% | 1.26 | −26.7% | 9/11 | 0.044 | 0.998 | no |
| A | atr2 | +688.6% | 1.13 | −25.5% | 7/11 | 0.062 | 0.991 | no |
| A | flip | +139.6% | 0.66 | −35.8% | 6/11 | 0.191 | 0.706 | no |
| A | atr2flip | +64.0% | 0.45 | −46.5% | 6/11 | 0.376 | 0.511 | no |
| B | atr3 | +797.5% | 1.33 | −29.8% | 9/11 | 0.017 | 0.982 | no |
| B | atr2 | +652.9% | 1.25 | −33.6% | 9/11 | 0.027 | 0.970 | no |
| B | flip | +350.2% | 0.95 | −31.4% | 8/11 | 0.091 | 0.885 | no |
| B | atr2flip | +234.7% | 0.81 | −35.1% | 7/11 | 0.138 | 0.808 | no |

References (outside gates): bare A +1089.2%/−20.2%; bare B +914.7%/−29.2%;
fixed±10% A +260.5%/−27.9%; fixed±10% B +675.7%/−25.9%.

## Block 2 — take rules (stop = atr3), top rows by eligibility relevance

| core | take | net | Sharpe | maxDD | folds+ | SPA | DSR | Holm | elig |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | **f1:1** | **+883.7%** | **1.25** | **−23.0%** | 8/11 | 0.038 ✓ | 0.997 ✓ | **0.092 ✗** | **YES** |
| A | f1:3 | +1015.6% | 1.30 | −26.5% | 9/11 | 0.039 | 0.998 | 0.092 | no |
| A | p1:1+BU | +942.7% | 1.26 | −26.7% | 9/11 | 0.044 | 0.998 | 0.094 | no |
| A | f1:2 | +893.3% | 1.25 | −26.5% | 9/11 | 0.043 | 0.997 | 0.094 | no |
| B | f1:3 | +834.2% | 1.37 | −29.8% | 9/11 | 0.014 | 0.985 | 0.056 | no |
| B | p1:2+BU | +794.9% | 1.33 | −29.8% | 9/11 | 0.017 | 0.982 | 0.061 | no |

(Full table in `development-metrics.csv`; every remaining row fails the −25% DD ceiling.)

## Findings

1. **Price stops do NOT fix crash-day drawdowns.** Crypto gaps: a −20…−30% day blows
   through any pre-placed stop distance in one close; the exit executes after the damage.
   All eight Block-1 rows still breach −25%. Stops also tax returns via churn
   (atr2 worse than atr3 everywhere).
2. **Funding-flip is a costly filter here**: constant churn bleeds fees and misses the
   premium days; strictly dominated by price-stop variants on both cores.
3. **Take-profits DO compress tails** when the trigger is tight (f1:1 locks gains before
   the next leg down): exactly one configuration lands inside the −25% ceiling.
4. The eligible candidate's economics: +883.7% over 5.5 years (~+46%/yr compounded),
   Sharpe 1.25, worst peak-to-trough −23%, positive in 8 of 11 half-years.
5. **Multiplicity remains the wall**: naive p = 0.0051 is strong, SPA and DSR pass
   comfortably at N = 30, but the Holm step-down reaches only 0.092, and heritage DSR
   at N = 6,082 is 0.0014 — program-wide, six thousand trials later, one survivor of
   this shape cannot be distinguished from the best of many tries without fresh data.

## Verdict consequences

`NO_SELECTION` under frozen rules; no substitution permitted. Queued families:
H-MR (daily mean reversion), H-XS (cross-sectional momentum), H-VOL (volatility-regime
conditioning), portfolio day-brake, cooldown variants. Any successor must freeze first,
declare these diagnostics, and accept heritage pricing ≥ 6,082 trials.

## Artifacts (`reports/artifacts/altcoin-carry-sl-001/`)

`input-manifest.json` · `statistics.json` · `eligibility-table.json` ·
`selection-dossier.json` · `verdict-final.json` · `run-metadata.json` ·
`development-metrics.csv` · `sweep-progress.json`

## Reproduction

```bash
uv sync --frozen --group dev
uv run python -m pytest                                             # 95 passed
uv run python -m research.altcoin_carry_sl_001 --validate-grid      # count = 30
uv run python -m research.altcoin_carry_sl_001 --stage sweep   --inputs-root <inputs> --cache-dir <cache>
uv run python -m research.altcoin_carry_sl_001 --stage finalize --inputs-root <inputs> --cache-dir <cache>
```
