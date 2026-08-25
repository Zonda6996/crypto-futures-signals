# ALTCOIN_XS_001 (H-XS "cross-sectional momentum") - final handoff

Status: **protocol executed end-to-end; final verdict `NO_SELECTION`** - 0 of 12
configurations pass eligibility; the XS family is CLOSED per protocol. Freeze proof
`8635b73`; engine `research/altcoin_xs_001.py`.

## Inputs

No downloads (daily closes + funding from the verified v2 layer). DECIDE window
2021-01-01 .. 2026-06-30. Sweep runtime ~1 s for 12 configurations.

## Results (net of 12 bps round trip)

| win | K | rebal | net | Sharpe | maxDD | folds+ | SPA | DSR | Holm | elig |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3 | 2 | 1 | -97.3% | -0.05 | -98.7% | 5/11 | 0.938 | 0.082 | 1.000 | no |
| 3 | 2 | 7 | +177.3% | 0.68 | -62.8% | 6/11 | 0.206 | 0.641 | 0.448 | no |
| 3 | 3 | 1 | -35.8% | 0.10 | -71.4% | 6/11 | 0.861 | 0.167 | 1.000 | no |
| 3 | 3 | 7 | +72.6% | 0.46 | -61.3% | 6/11 | 0.467 | 0.438 | 1.000 | no |
| 7 | 2 | 1 | -95.6% | 0.13 | -98.5% | 7/11 | 0.836 | 0.187 | 1.000 | no |
| 7 | 2 | 7 | INVALID (equity_non_positive) | | | | | | | no |
| 7 | 3 | 1 | -23.5% | 0.18 | -69.9% | 8/11 | 0.804 | 0.216 | 1.000 | no |
| 7 | 3 | 7 | -54.7% | -0.03 | -85.2% | 5/11 | 0.931 | 0.091 | 1.000 | no |
| 14 | 2 | 1 | +245.0% | 0.74 | -47.4% | 7/11 | 0.188 | 0.689 | 0.448 | no |
| **14** | **2** | **7** | **+485.1%** | **1.01** | **-43.6%** | **9/11** | **0.026** | 0.872 | 0.048 | **no (DD)** |
| 14 | 3 | 1 | -13.0% | 0.22 | -70.7% | 7/11 | 0.774 | 0.250 | 1.000 | no |
| 14 | 3 | 7 | -5.0% | 0.26 | -83.8% | 8/11 | 0.774 | 0.278 | 1.000 | no |

References: B&H basket +583.0% (DD -83.9%); B&H BTC +99.8% (DD -76.7%).

## Findings

1. **Daily-rebalanced momentum is suicide**: -95..-98% net - churn costs plus
   momentum crashes inside the week. The effect, if any, lives only on slow settings.
2. **The only decent arm (14d window, weekly, K=2)**: +485%, Sharpe 1.01, 9/11 folds,
   SPA 0.026 - but DD -43.6% fails the -25% ceiling by 18.6 points and DSR misses
   (0.872). Eligibility: 0/12.
3. **The +485% is mostly market beta**: buy-and-hold of the same basket made +583%
   (with worse DD). The cross-sectional spread adds little beyond riding the market
   up on 10 majors.
4. **Shorting losers remains toxic in bounces**: one configuration invalidated by a
   short squeeze through the equity floor (7/2/7), mirroring MR-TF-001.
5. K=3 dilutes the signal everywhere (K=3 rows uniformly weaker than K=2).

## Consequences

`NO_SELECTION`: cross-sectional momentum is unproven and the XS family CLOSES on this
universe per protocol. No re-tuning on DECIDE-overlapping windows. Remaining queue:
H-VOL, day-brake, cooldowns, atr3+flip combo (all low-priority); the highest-EV
directions are portfolio integration with the external D6 line (corr 0.084) and
forward accumulation of the carry SELECT.

## Artifacts (`reports/artifacts/altcoin-xs-001/`)

`input-manifest.json` - `statistics.json` - `eligibility-table.json` -
`selection-dossier.json` - `verdict-final.json` - `run-metadata.json` -
`development-metrics.csv` - `sweep-progress.json`

## Reproduction

```bash
uv run python -m pytest                                              # 147 passed
uv run python -m research.altcoin_xs_001 --validate-grid             # count = 12
uv run python -m research.altcoin_xs_001 --stage sweep   --inputs-root <inputs> --cache-dir <cache>
uv run python -m research.altcoin_xs_001 --stage finalize --inputs-root <inputs> --cache-dir <cache>
```
