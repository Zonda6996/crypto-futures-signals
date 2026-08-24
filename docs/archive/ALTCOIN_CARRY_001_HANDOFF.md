# ALTCOIN_CARRY_001 (H-CARRY "cross-sectional funding carry") — final handoff

Status: **protocol executed end-to-end; final verdict `NO_SELECTION`** ("hypothesis
unproven as deployable"). Freeze proof: commit `26b78ca`; erratum + engine `a978f33`
(both pre-analysis); protocol doc `docs/ALTCOIN_CARRY_001_FROZEN_PROTOCOL.md`.

## Inputs

Identical immutable archives as ALT-MULTITF-007 (hashes verified there); no new
downloads. Funding series cover all ten symbols from listing through 2026-07; DECIDE
window 2021-01-01 .. 2026-06-30 (2,007 daily observations).

## Execution summary

| Stage | Result |
| --- | --- |
| Grid validation | exactly **12** configurations |
| DECIDE sweep | 11 valid, 1 invalidated (`equity_non_positive`, see diagnostics), ~1 s wall |
| Eligibility | **1 of 11** active configurations passes all criteria |
| Statistical gates | the eligible candidate fails SPA only (`spa_p = 0.056 > 0.05`) |
| Final verdict | `NO_SELECTION` |

## Results (net of primary costs 4+2 bps on traded notional)

| lb | k | rebal | net return | ann Sharpe | max DD | folds+ | SPA p | DSR | Holm |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2 | 1 | +162% | 0.53 | −60.5% | 5/11 | 0.401 | 0.356 | 0.405 |
| 1 | 2 | 7 | INVALID | — | — | — | — | — | — |
| 1 | 3 | 1 | +138% | 0.57 | −40.8% | 5/11 | 0.330 | 0.404 | 0.405 |
| 1 | 3 | 7 | −77% | −0.07 | −93.3% | 8/11 | 0.903 | 0.039 | 0.556 |
| 3 | 2 | 1 | +698% | 0.91 | −30.9% | 9/11 | 0.137 | 0.817 | 0.184 |
| 3 | 2 | 7 | +97% | 0.51 | −55.7% | 9/11 | 0.356 | 0.367 | 0.405 |
| 3 | 3 | 1 | **+1089%** | **1.32** | **−20.2%** | 9/11 | 0.056 | 0.988 | 0.038 |
| 3 | 3 | 7 | +115% | 0.61 | −38.8% | 7/11 | 0.308 | 0.456 | 0.405 |
| 7 | 2 | 1 | +915% | 1.39 | −29.2% | 9/11 | **0.037** | **0.958** | **0.013** |
| 7 | 2 | 7 | +231% | 0.82 | −38.3% | 8/11 | 0.128 | 0.653 | 0.181 |
| 7 | 3 | 1 | +678% | 1.13 | −27.7% | 9/11 | 0.088 | 0.941 | 0.089 |
| 7 | 3 | 7 | +281% | 0.99 | −30.6% | 8/11 | 0.102 | 0.788 | 0.125 |

Heritage DSR at N = 6,044 (all trials ever: 005+006+007+CARRY-001): best values
0.0065 (7,2,1) and 0.0606 (3,3,1) — after pricing the cumulative program-wide search,
neither reaches deployability confidence.

## Why the verdict stands (frozen rules, no relaxation)

- The single eligible candidate (3,3,1) missed SPA by 0.006 (0.056 vs ≤0.05 required);
  substitution by (7,2,1) — which passes SPA/DSR/Holm — is forbidden because it failed
  the eligibility drawdown gate (−29.2% < −25%).
- Temporal robustness gate (≥7/11 half-years positive AND median fold SR > 0) was
  reached only inside candidates already excluded above.

## Descriptive diagnostics (post-verdict, no selection impact)

1. **Invalidated configuration (1,2,7):** between weekly rebalances the short DOGE
   position drifted from −25% to ≈ −200% notional during the April 2021 DOGE melt-up
   (+101% on 2021-04-16 alone); portfolio growth hit −96.9% in one day ⇒ deterministic
   `equity_non_positive` invalidation. Economically: an unmanaged concentrated short
   would have been liquidated long before; the frozen contract correctly refuses to
   count such a path as tradable.
2. **Extreme funding:** SOLUSDT printed a −17.2% aggregate daily funding rate on
   2022-11-09 (FTX week) — absorbed without invalidation by every surviving path.

## Interpretation

The contrast with the closed trend family is stark:

- 10 of 11 active carry configurations are net-positive over 5.5 years; trend produced
  0 of 8.
- Two configurations pass the entire multiplicity-corrected statistical stack at
  N = 12 (SPA ≤ 0.05, DSR ≥ 0.95, Holm ≤ 0.05) with 8–9 of 11 positive half-years.
- What blocks deployment under frozen rules: single-digit-basis-point edges do not
  survive program-level multiplicity (heritage N = 6,044), and raw carry drawdowns sit
  at −27…−38%, above the −25% eligibility ceiling except exactly one configuration.

H-CARRY is therefore **not proven deployable**, but it is the first family in this
program showing a gross premium that survives real costs. Any successor (e.g., an
explicitly risk-managed carry variant) must be a NEW freeze that declares this
diagnostics as design input, keeps every gate unchanged, and accepts heritage
N ≥ 6,044 pricing. Re-running or re-tuning on DECIDE-overlapping windows remains
prohibited.

## Artifacts (`reports/artifacts/altcoin-carry-001/`)

`input-manifest.json` · `statistics.json` · `eligibility-table.json` ·
`selection-dossier.json` · `verdict-final.json` · `run-metadata.json` ·
`development-metrics.csv` · `sweep-progress.json`

## Reproduction

```bash
uv sync --frozen --group dev
uv run python -m pytest                                            # 68 passed
uv run python -m research.altcoin_carry_001 --validate-grid        # count = 12
uv run python -m research.altcoin_carry_001 --stage sweep   --inputs-root <inputs> --cache-dir <cache>
uv run python -m research.altcoin_carry_001 --stage finalize --inputs-root <inputs> --cache-dir <cache>
```
