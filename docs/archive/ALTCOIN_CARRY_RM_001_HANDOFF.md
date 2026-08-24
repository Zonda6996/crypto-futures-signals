# ALTCOIN_CARRY_RM_001 (H-CARRY-RM "risk-managed funding carry") — final handoff

Status: **protocol executed end-to-end; final verdict `NO_SELECTION`** ("risk-managed
carry unproven as deployable"). Freeze proof `68482d4`; erratum `9209620` (dd computed
on provisional pre-cost equity); engine `research/altcoin_carry_rm_001.py`.

## Inputs

Identical immutable archives as CARRY-001; no downloads. DECIDE window unchanged
(2021-01-01 .. 2026-06-30, 2,007 daily observations). Two bare-core reference rows are
emitted outside the grid; both reproduce CARRY-001 results exactly (A: +1089.2%,
DD −20.2%; B: +914.7%, DD −29.2%) — engine equivalence verified on real data.

## Execution summary

| Stage | Result |
| --- | --- |
| Grid validation | exactly **8** configurations |
| DECIDE sweep | 8/8 valid, ~1 s wall |
| Eligibility | **4 of 8** pass (all four core-A overlays) — was 1 of 12 in CARRY-001 |
| Statistical gates | none survive: best DSR 0.933 (< 0.95), best SPA 0.111 (> 0.05) |
| Final verdict | `NO_SELECTION` |

## Results (net of primary costs)

| core | dd_start | dd_stop | net | ann Sharpe | max DD | folds+ | SPA | DSR | Holm | elig |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A(3/3/1) | 5% | 15% | +290% | 0.89 | **−15.0%** | 6/11 | 0.166 | 0.861 | 0.300 | YES |
| A(3/3/1) | 5% | 20% | +462% | 1.03 | **−16.9%** | 8/11 | 0.111 | 0.933 | 0.185 | YES |
| A(3/3,1) | 10% | 15% | +280% | 0.89 | −15.5% | 1/11 | 0.170 | 0.897 | 0.300 | YES |
| A(3/3/1) | 10% | 20% | +398% | 0.96 | −18.8% | 7/11 | 0.135 | 0.884 | 0.224 | YES |
| B(7/2/1) | 5% | 15% | −2.7% | 0.03 | −25.8% | 1/11 | 0.755 | 0.079 | 1.000 | no |
| B(7/2/1) | 5% | 20% | −0.5% | 0.06 | −25.8% | 1/11 | 0.736 | 0.093 | 1.000 | no |
| B(7/2/1) | 10% | 15% | +1.6% | 0.09 | −25.8% | 1/11 | 0.707 | 0.107 | 1.000 | no |
| B(7/2/1) | 10% | 20% | +1.6% | 0.09 | −25.8% | 1/11 | 0.707 | 0.107 | 1.000 | no |

Heritage report-only DSR at N = 6,052 (005+006+007+CARRY-001+RM-001): variance across
6,051 published Sharpes (the invalidated CARRY-001 configuration contributes a trial
but no Sharpe); every current probability far below any deployment bar.

## What the overlay achieved and what it cost

1. **The risk fix works mechanically.** Every core-A overlay cut max drawdown from
   −20.2% to −15…−19% while keeping net expectancy strongly positive (+280…+462%) and
   Sharpe improving (up to 1.03). Four configurations now clear eligibility where
   CARRY-001 had exactly one.
2. **The de-risking tax is real.** Cutting exposure into weakness forfeits part of the
   recovery: net falls by ~55–75% versus the bare core, and temporal consistency
   becomes fragile (two variants collapse to 1/11 positive half-years — the overlay
   sat flat through their best segments).
3. **Core B is incompatible with this overlay.** Its concentrated edge needed full-size
   exposure through volatility; the overlay whipsawed it to zero while its single-gap
   drawdown (−25.8%, hit before any cushion existed) stayed above the ceiling anyway.
4. **Statistical certainty remains out of reach.** With N = 6,052 cumulative trials
   priced in, even the strongest variant (DSR 0.933 at N = 8 decision gate) cannot
   reach 95% confidence under frozen rules. This is the honest price of a thin,
   crash-sensitive premium observed after four search rounds.

## Verdict consequences

Per the frozen decision rule: H-CARRY-RM is unproven as deployable. Queued candidate
families (each requires its own pre-analysis freeze): H-CARRY-SL (per-position stops /
take-profits, possibly partial profit-taking — explicitly requested by the project
owner), H-MR (daily mean reversion), H-XS (cross-sectional momentum), H-VOL
(volatility-regime conditioning). No re-tuning on DECIDE-overlapping windows.

## Artifacts (`reports/artifacts/altcoin-carry-rm-001/`)

`input-manifest.json` · `statistics.json` · `eligibility-table.json` ·
`selection-dossier.json` · `verdict-final.json` · `run-metadata.json` ·
`development-metrics.csv` · `sweep-progress.json`

## Reproduction

```bash
uv sync --frozen --group dev
uv run python -m pytest                                             # 80 passed
uv run python -m research.altcoin_carry_rm_001 --validate-grid      # count = 8
uv run python -m research.altcoin_carry_rm_001 --stage sweep   --inputs-root <inputs> --cache-dir <cache>
uv run python -m research.altcoin_carry_rm_001 --stage finalize --inputs-root <inputs> --cache-dir <cache>
```
