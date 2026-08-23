# ALTCOIN_CARRY_FINAL_001 (H-CARRY-FINAL "hardened carry") — final handoff

Status: **protocol executed end-to-end; final verdict `SELECT`** — the first and only
SELECT of the program. Selected configuration: **core A + atr3 stop + full take 1:1
+ BTC beta-hedge ON + inverse-volatility weights + gate always**.
Freeze proof `240598a` (erratum included); engine `research/altcoin_carry_final_001.py`.

## Inputs

No downloads (all archives local, hashes inherited); no exchangeInfo snapshot required
by this protocol. DECIDE window 2021-01-01 .. 2026-06-30 (2,007 daily observations).

## Execution summary

| Stage | Result |
| --- | --- |
| Grid validation | exactly **8** configurations |
| Eligibility | **4 of 8** pass |
| Gates | rank-1 eligible passes **everything**: SPA 0.025, DSR 1.000, Holm 0.024, bootstrap CI-low > 0, neighbours ✓, temporal 9/11 ✓, all four stress scenarios ✓ |
| Final verdict | **`SELECT`** (`verdict-final.json`) |
| Regression anchor | all-off corner reproduced the SL-001 champion exactly (+883.7%, DD −23.0%, Sharpe 1.25) |

## Selected configuration — full frozen specification

```
Universe        : 10 frozen USDT-M perpetuals (never reselected)
Signal          : 3-day trailing mean funding, ranked daily at 00:00 UTC close
Book            : short top-3 payers / long bottom-3, dollar-neutral, gross 1.0
Weights         : inverse-volatility (30-day sigma of daily returns, gross preserved)
Stops           : 3 × Wilder ATR(14) from entry, checked on daily closes
Take            : full position closed at +1 × stop-distance (single-shot)
Episodes        : rank-drop exits, same-close refill ban after manual exits,
                  daily trim to target, anti-blowup cap at 2× target
Hedge           : BTC-perp leg, notional = −(held-weights avg 90d beta vs BTC) × gross,
                  resized daily, no stops on the hedge leg
Gate            : none (always deployed)
Costs (frozen)  : taker 4 bps + slippage 2 bps per unit traded notional
```

## Results — all 8 configurations (net of primary costs, 5.5 years)

| hedge | weights | gate | net | ~CAGR | Sharpe | maxDD | folds+ | SPA | DSR | Holm | elig |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| off | equal | always | +883.7% | +48% | 1.25 | −23.0% | 8/11 | 0.031 | 1.000 | 0.031 | YES |
| off | equal | disper | +607.1% | +39% | 1.13 | −30.9% | 9/11 | 0.061 | 1.000 | 0.037 | no |
| off | invvol | always | +1070.0% | +52% | 1.59 | −21.9% | 9/11 | 0.014 | 1.000 | 0.010 | YES |
| off | invvol | disper | +740.1% | +45% | 1.18 | −62.6% | 8/11 | 0.055 | 0.993 | 0.037 | no |
| **on** | equal | always | +845.1% | +47% | 1.22 | −24.0% | 9/11 | 0.038 | 1.000 | 0.031 | YES |
| on | equal | disper | +579.1% | +38% | 1.11 | −26.2% | 8/11 | 0.078 | 0.999 | 0.037 | no |
| **on** | **invvol** | **always** | **+763.3%** | **+48%** | **1.44** | **−20.9%** | **9/11** | **0.025** | **1.000** | **0.024** | **YES → SELECT** |
| on | invvol | disper | +513.7% | +34% | 1.15 | −30.3% | 6/11 | 0.075 | 0.995 | 0.037 | no |

Winner deep-dive: bootstrap mean-return CI [+0.00036; +0.00222] per day (lower > 0);
stress nets: fees×2 +435.6%, slippage×3 +435.6%, funding-half +613.7%, funding-flip
+303.0% — all positive; maker track +1,134.8% (report-only); heritage DSR at
N = 6,090 = 0.019 (report-only).

References (outside gates): bare A +1,089.2%/−20.2%; bare B +914.7%/−29.2%;
RISK arm (p1:2+BU) +939.2%/−26.7%.

## Findings

1. **Inverse-volatility weighting is the real hardening lever**: +0.34 Sharpe over the
   champion (1.59 vs 1.25 unhedged; 1.44 hedged), DD down to −21.9/−20.9%.
2. **Beta hedge adds robustness on top**: slightly lower net than unhedged inv-vol
   (−307 p.p. over 5.5y — the hedge premium), but best drawdown of the family (−20.9%),
   best Holm (0.024), and 9/11 temporal consistency. The ordering rule picked it rank-1.
3. **The dispersion gate FAILED**: blocking entries in low-dispersion regimes cut
   returns and *increased* drawdowns (the gate strands stale episodes while blocking
   the re-entries that would recover them). Informative negative — do not reuse.
4. **Holm is now passed, not dodged**: naive p = 0.0019-level evidence with N = 8
   in-protocol trials; the multiplicity step that killed SL-001 (0.092) clears at 0.024
   because the strategy got genuinely better, not because gates moved. Gates, costs,
   seeds and windows are byte-identical to the frozen stack.

## Honest caveats

- Single in-sample pass over 2021–2026-06; heritage DSR at N = 6,090 is 0.019 — after
  pricing the whole program, confidence remains moderate. The frozen protocol declares
  this the LAST in-sample pass; validation continues forward-only.
- Monitor reserve 2026-07…08 remains untouched and is the first out-of-sample test.
- Hedge leg introduces BTC-short exposure sizing risk in extreme squeezes (no stops on
  the hedge by design); position sizing for live deployment must respect the −21%
  historical DD with additional margin buffer.

## Consequences

`SELECT` ⇒ this exact configuration becomes the **TIDAL SAFE-mode candidate** and the
subject of the forward monitoring plan (reserve 2026-07…08, then live paper-forward).
RISK mode remains the published SL-001 RISK arm (p1:2+BU) pending its own forward
validation. No further carry tuning on overlapping windows — protocol prohibits it.

## Artifacts (`reports/artifacts/altcoin-carry-final-001/`)

`input-manifest.json` · `statistics.json` · `eligibility-table.json` ·
`selection-dossier.json` · `verdict-final.json` · `run-metadata.json` ·
`development-metrics.csv` · `sweep-progress.json`

## Reproduction

```bash
uv sync --frozen --group dev
uv run python -m pytest                                              # 110 passed
uv run python -m research.altcoin_carry_final_001 --validate-grid    # count = 8
uv run python -m research.altcoin_carry_final_001 --stage sweep   --inputs-root <inputs> --cache-dir <cache>
uv run python -m research.altcoin_carry_final_001 --stage finalize --inputs-root <inputs> --cache-dir <cache>
```
