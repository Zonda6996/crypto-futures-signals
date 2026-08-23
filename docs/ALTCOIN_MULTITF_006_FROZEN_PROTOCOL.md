# ALTCOIN_MULTITF_006 frozen protocol (H1 "Daily trend, long-biased")

Status: **frozen before any 2024+ data was analysed**. This protocol is committed to
git prior to acquisition of the new inputs it references; the commit timestamp is the
freeze proof. It inherits the causal engine, execution contract and cost model of
`ALTCOIN_MULTITF_FROZEN_PROTOCOL.md` (ALT-MULTITF-005) without modification. No gate,
cost, seed or criterion may be weakened after this commit.

## Provenance rationale

ALT-MULTITF-005 completed a full deterministic sweep on development data 2021–2023 and
ended in `NO_SELECTION` (see `ALTCOIN_MULTITF_005_PHASE4_PART2_HANDOFF.md`). Descriptive
post-mortem (`reports/artifacts/altcoin-multitf-005-phase4/diagnostics-failure-analysis.md`)
showed positive mid-price edge destroyed by turnover-proportional costs, with results
improving monotonically as trade frequency falls. H1 therefore moves the hypothesis one
regime down in frequency instead of re-tuning the failed grid. The windows below were
never read by any prior phase (seal audit: zero bars loaded outside the 005 dev interval;
2025–2026 never used by anyone).

## Data contract

- Universe (unchanged, never reselected): `BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT,
  ADAUSDT, DOGEUSDT, AVAXUSDT, LINKUSDT, DOTUSDT` USDT-margined perpetuals.
- Bars: 5m execution; **1d signal; 7d regime** (7d = epoch-aligned 2016×5m buckets; partial
  boundary buckets are dropped by the deterministic aggregator). A bar is available only at
  its close.
- Sources: public Binance Vision monthly klines/fundingRate zips + one fresh public
  `exchangeInfo` snapshot taken at freeze time. All inputs immutable local files with
  SHA-256 in manifests; missing required input invalidates a configuration; no
  forward-fill across gaps.
- Supplement v2 archive `altcoin-multitf-006-supplement`: BTC/ETH/DOT raw+normalized for
  2020-02..2026-08 (full history so that slow weekly averages warm up) and all ten symbols
  for 2026-01..2026-08. Disjoint from prior archives by construction; merge refuses
  overwrites/conflicts.

## Windows

| Window | UTC interval | Role |
| --- | --- | --- |
| DEV (search + gates) | `2024-01-01T00:00:00Z` .. `2024-12-31T23:59:59Z` | full statistical machinery, candidate selection |
| CONFIRM | `2025-01-01T00:00:00Z` .. `2026-06-30T23:59:59Z` | mandatory re-validation of the single DEV winner only |

Engine run span includes indicator warmup from earliest acquired history (2020-02);
accounting (equity, metrics) counts only trades whose entry lies inside the accounting
window. Indicators are therefore fully warmed at each window start; pre-window decisions
are never taken.

## Frozen grid — 192 configurations

Family A (regime-aligned trend continuation) only:

```
signal_tf_minutes : 1440            regime_tf_minutes : 10080
fast × slow       : {10,20} × {50,100,200}   (all six pairs valid)
entry_threshold   : {0.01, 0.02}
exit_threshold    : {0.0}   (single value; axis not consumed by the engine)
stop_atr          : {2.0, 3.0}      take_atr : {4.0, 6.0}
max_holding_bars  : {14400, 28800}  (= 10 / 20 days of 5m execution bars)
side              : {"long", "both"}
```

Count check: 6 × 2 × 2 × 2 × 2 × 2 = **192**. Part 2 must stop on any other count.
Expected trades per configuration ≈ hundreds, not tens of thousands.

## Costs (dual-track, fixed ex ante)

- Primary decision track (identical to 005): fee 4 bps/fill taker, slippage 2 bps/fill.
- Secondary report-only track: maker fee 2 bps/fill, slippage 1 bps/fill. Never a gate;
  reported alongside the primary numbers for transparency only.

## Seeds

Sweep/ordering `20260823`; bootstrap `20260824`; SPA `20260825`. All aggregation orders
lexicographically stable. Non-finite values invalidate the affected configuration.

## Statistical contract and gates (no weakening vs 005)

Eligibility: ≥100 aggregate trades; net return > 0; annualized daily Sharpe (√365) > 0.5;
max drawdown ≥ −25% on the daily closed-equity curve; ≥6 active assets; max asset share of
positive PnL ≤ 40%.

Mandatory gates for the selected candidate, computed across the complete valid search
space where applicable: SPA consistent p ≤ 0.05 (Hansen stationary bootstrap, screened);
Deflated Sharpe probability ≥ 0.95 with N = number of valid configurations; Holm-adjusted
p ≤ 0.05; circular block-bootstrap return CI lower bound > 0 (seed `20260824`, B=2000,
block length round(n^(1/3))); ≥60% profitable parameter neighbors (neighbors differ in
exactly one grid axis; denominator = valid evaluated neighbors); stress scenarios fees×2,
slippage×3, funding magnitude×2, funding sign-flip×2 — each must keep aggregate net > 0;
temporal consistency: median fold Sharpe > 0 and ≥4 of 6 folds positive (folds = six
two-month segments of 2024); concentration/coverage as in eligibility; long/short gate:
for side="both" both directional nets must be > 0.

Ordering (pre-registered tie-break): eligible first, then median fold Sharpe desc,
aggregate Sharpe desc, net return desc, drawdown closest to zero, configuration key asc.
If several candidates pass every DEV gate, rank 1 wins deterministically; if none pass,
the outcome is `NO_SELECTION`.

## Confirmation gate (final)

The unique DEV winner is re-evaluated unchanged on CONFIRM. It must satisfy there:
net return > 0, annualized Sharpe > 0.5, max DD ≥ −25%, bootstrap CI lower bound > 0
(same seed/B/block rule on confirm-window trade sequence). Failure ⇒ final verdict
`NO_SELECTION`; substitution by another candidate is forbidden.

## Prohibitions

Identical to ALT-MULTITF-005: no changes to engine/grid/windows/universe/costs/seeds/
gates/correction/bootstrap to obtain a winner; no selection on CONFIRM data under any
circumstances (its metrics exist only inside the final gate); smoke runs are not sweeps;
stop on hash/grid-count mismatch; artifacts must record exact SHA-256 of every input,
commands, counts, resume checks and the deterministic decision.

Artifacts directory: `reports/artifacts/altcoin-multitf-006/`.
