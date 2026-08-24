# ALTCOIN_MULTITF_007 ("Definitive One-Shot") — final handoff and line closure

Status: **protocol executed end-to-end; final verdict `NO_SELECTION`; per the frozen
decision rule the altcoin multi-timeframe trend line is CLOSED PERMANENTLY.**
Freeze proof: commit `f0628f5` (protocol + freeze-time exchange rules, pre-analysis),
protocol doc `docs/ALTCOIN_MULTITF_007_FROZEN_PROTOCOL.md`.

## Inputs (no downloads required, all verified before any read)

- Primary archive SHA-256 `665ac7b7…83743d` (1,541,152,490 B) — verified match.
- Supplement v1 `a753585a…47bd5b` (113,083,086 B) — verified match.
- Supplement v2 `487046fa…0d10c56` (573,920,939 B) — verified match.
- Freeze-time public `exchangeInfo` snapshot raw SHA-256
  `3eb3bcf2…5b2daf` (1,077,582 B); extracted binding rules committed at freeze
  (`reports/artifacts/altcoin-multitf-007/input/exchange-rules-frozen.json`,
  SHA-256 `3109eeae…4b0a6`); all ten universe symbols `TRADING` at freeze time.

## Execution summary

| Stage | Result |
| --- | --- |
| Grid validation | exactly **8** configurations |
| DECIDE sweep (accounting 2021-01-01 .. 2026-06-30; engine span from earliest history) | 8/8 valid, 0 invalid, 0 zero-trade, ~53 s wall |
| Eligibility | **0 of 8** pass |
| Statistical gates | not reached (no eligible candidate); SPA p ≥ 0.80 for every configuration anyway |
| Final verdict | `NO_SELECTION` (`verdict-final.json`) |

## Results by configuration (net of primary costs: fee 4 bps + slippage 2 bps per fill)

| sma_pair | entry | hold | trades | net return | ann. Sharpe | max DD | positive folds | median fold SR |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20/100 | 0.005 | 10d | 402 | −1.5% | −0.11 | −36.0% | 3/11 | ≈0 |
| 20/100 | 0.005 | 40d | 177 | −3.2% | −0.29 | −47.0% | 3/11 | ≈0 |
| 20/100 | 0.01 | 10d | 388 | −1.7% | −0.14 | −37.4% | 2/11 | ≈0 |
| 20/100 | 0.01 | 40d | 169 | −3.2% | −0.32 | −47.0% | 2/11 | ≈0 |
| 50/200 | 0.005 | 10d | 304 | −4.5% | −0.70 | −52.6% | 3/11 | ≈0 |
| 50/200 | 0.005 | 40d | 120 | −5.8% | −0.87 | −63.6% | 3/11 | ≈0 |
| 50/200 | 0.01 | 10d | 302 | −4.4% | −0.67 | −51.5% | 3/11 | ≈0 |
| 50/200 | 0.01 | 40d | 118 | −5.8% | −0.90 | −63.7% | 3/11 | ≈0 |

Heritage report-only DSR at N = 6,032 (all configurations ever evaluated by 005+006+007):
probabilities between `1.2e−19` and `1.9e−07` — indistinguishable from noise at the full
search scale. DSR at N = 8 also ≤ 0.10 everywhere.

## Interpretation

1. This was the maximum-power test: ~1,980 accounting days, N = 8 canonical priors,
   no multiplicity wall left to hide behind — and nothing survived even eligibility
   (net > 0, Sharpe > 0.5, DD ≥ −25%).
2. The failure mode is consistent with the published 005 post-mortem: long-only trend
   continuation on daily crypto carries deep drawdowns (−36…−64%) while net PnL after
   costs stays negative; temporal consistency collapses to 2–3 positive half-years of 11.
   The hypothesis family does not merely lack statistical significance — it lacks a
   gross edge large enough to cover its own drawdown profile.
3. Both prior windows stay honest: 2021–2023 was burned by 005, 2024 by 006, and 007's
   single pass over 2021–2026-06 is now burned as well. The monitor reserve 2026‑07…08
   remains untouched and unanalysed.

## Line closure (per protocol decision rule)

`NO_SELECTION` ⇒ **the altcoin multi-timeframe trend line (ALT-MULTITF) is closed
permanently**. No successor protocol may re-open selection on any window overlapping
2021‑01…2026‑06. The recorded alternatives if a related hypothesis is ever revisited on a
NEW freeze with NEW data going forward only: H-carry (funding as signal) or H-XS
(cross-sectional momentum). Neither may reuse any interval above.

## Artifacts (`reports/artifacts/altcoin-multitf-007/`)

`input/exchange-rules-frozen.json` · `input-manifest.json` · `statistics.json` ·
`eligibility-table.json` · `selection-dossier.json` · `verdict-final.json` ·
`run-metadata.json` · `development-metrics.csv` · `sweep-progress.json`

## Reproduction

```bash
uv sync --frozen --group dev
uv run python -m pytest                                  # 49 passed
uv run python -m research.altcoin_multitf_phase7 --validate-grid   # count = 8
uv run python -m research.altcoin_multitf_phase7 --stage sweep    --inputs-root <inputs> --cache-dir <cache>
uv run python -m research.altcoin_multitf_phase7 --stage finalize --inputs-root <inputs> --cache-dir <cache>
```

Deterministic resume guarded by checkpoint identity (schema/seed/grid/window).
