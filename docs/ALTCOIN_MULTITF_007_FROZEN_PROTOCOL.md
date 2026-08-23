# ALTCOIN_MULTITF_007 frozen protocol ("Definitive One-Shot", full-history daily trend)

Status: **frozen before any new window analysis**. This protocol is committed to git
prior to reading any market data beyond what earlier protocols already analysed; the
commit timestamp is the freeze proof. It inherits the causal engine, execution contract
and cost model of `ALTCOIN_MULTITF_FROZEN_PROTOCOL.md` (005) as carried unchanged into
`ALTCOIN_MULTITF_006_FROZEN_PROTOCOL.md`. No gate, cost, seed or criterion may be
weakened after this commit.

## Provenance rationale and declared limitation

ALT-MULTITF-005 (dev 2021–2023, 5,832 configurations) and ALT-MULTITF-006 (dev 2024,
192 configurations) both ended in `NO_SELECTION`. Published diagnostics show: (a) in 005,
positive mid-price edge was destroyed by turnover-proportional costs, improving
monotonically as trade frequency falls; (b) in 006, one year of data could not separate
a weak edge from noise after multiplicity correction.

**Declared limitation:** the 007 design below is informed by those published diagnostics
(lower trade frequency, canonical slow pairs, wider holding range). This is disclosed as
an irreducible property of any successor protocol after two executed searches; it is a
design prior, not a data read. The intervals 2025‑01…2026‑06 were never loaded by any
prior phase (006 DEV sweep clipped series to 2025‑01‑01; the confirmation stage exited
before constructing datasets — verifiable in code and by `verdict-final.json`), and
2026‑07…08 has never been acquired by anyone.

**One-shot rationale:** with T ≈ 1,980 accounting days even a moderate persistent edge
becomes statistically detectable at small N, while eleven half-year segments provide an
internal temporal-robustness substitute for a missing out-of-sample interval. If 007 ends
in `NO_SELECTION`, the altcoin trend line is closed permanently (see Decision rule).

## Data contract

- Universe (unchanged, never reselected): `BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT,
  ADAUSDT, DOGEUSDT, AVAXUSDT, LINKUSDT, DOTUSDT` USDT-margined perpetuals.
- Bars: 5m execution; **1d signal; 7d regime** (epoch-aligned 2016×5m buckets). A bar is
  available only at its close.
- Sources: exclusively the existing immutable archives — primary `altcoin-multitf-005`
  (SHA-256 `665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d`,
  1,541,152,490 bytes), supplement v1 `altcoin-multitf-005-supplement`
  (`a753585a11beb7bad74f9262920324fe8315a681b6dd108db072790bad47bd5b`, 113,083,086
  bytes) and supplement v2 `altcoin-multitf-006-supplement`
  (`487046fad5659e427075ca2b2b676bb3213da85276848129ba5eb21f00d10c56`, 573,920,939
  bytes) — merged under the strict no-overwrite policy, plus **one fresh public
  `exchangeInfo` snapshot taken at freeze time**. The snapshot is hashed; the extracted
  rules for the ten universe symbols are committed alongside this protocol and are the
  binding order-validation inputs of every 007 evaluation. Frozen snapshot identity:
  raw SHA-256 `3eb3bcf246495fb0e9e99a38f7d6c4cd741ced5f4256b461d3cf8643df5b2daf`
  (1,077,582 bytes); extracted rules file
  `reports/artifacts/altcoin-multitf-007/input/exchange-rules-frozen.json` SHA-256
  `3109eeae512270d1fad0db5f28ffe3265d6a18f0e660c6275356f0cbd1a4b0a6`; all ten symbols
  `TRADING` at freeze time. No other download is required
  or permitted; missing required input invalidates a configuration; no forward-fill
  across gaps.
- Known warmup asymmetry (declared, accepted): series start at each contract's earliest
  acquired history (2020‑02 for BTC/ETH/XRP/ADA/LINK; 2020‑07…09 for DOGE/DOT/SOL/AVAX).
  The SMA(200) daily signal therefore completes warmup before 2021‑04‑15 at the latest on
  every symbol. Decisions are never taken before indicator warmup; accounting counts only
  trades whose entry lies inside the decision window.

## Windows

| Interval | UTC | Role |
| --- | --- | --- |
| Engine span | from each symbol's earliest acquired history | indicator warmup only |
| DECIDE (single pass) | `2021-01-01T00:00:00Z` .. `2026-06-30T23:59:59Z` | full statistical machinery and the only selection ever performed by 007 |
| MONITOR RESERVE | `2026-07-01T00:00:00Z` .. | untouched; reserved exclusively for forward monitoring after a SELECT verdict |

There is **no confirmation stage**. Using the monitor reserve (or any post-hoc interval)
to rescue a failed candidate is prohibited.

## Frozen grid — exactly 8 configurations

Family A (regime-aligned trend continuation), long-only:

```
signal_tf_minutes : 1440            regime_tf_minutes : 10080
sma_pair          : {(20,100), (50,200)}
entry_threshold   : {0.005, 0.01}
exit_threshold    : {0.0}
stop_atr          : {3.0}           take_atr : {6.0}
max_holding_bars  : {2880, 11520}   (= 10 / 40 days of 5m execution bars)
side              : {"long"}
```

Count check: 2 × 2 × 2 = **8**. The runner must stop on any other count.
Grid axes for the neighbor topology are exactly: `sma_pair` (the pair varies as one
economic axis), `entry_threshold`, `max_holding_bars`; every configuration therefore has
exactly three single-axis neighbors inside the grid.

## Costs (dual-track, fixed ex ante)

- Primary decision track (identical to 005/006): fee 4 bps/fill taker, slippage 2 bps/fill.
- Secondary report-only track: maker fee 2 bps/fill, slippage 1 bps/fill. Never a gate.

## Seeds

Sweep/ordering `20260907`; bootstrap `20260908`; SPA `20260909`. All aggregation orders
lexicographically stable. Non-finite values invalidate the affected configuration.

## Statistical contract and gates (no weakening vs 005/006)

Eligibility (per configuration, over the full DECIDE window): ≥100 aggregate trades;
net return > 0; annualized daily Sharpe (√365) > 0.5; max drawdown ≥ −25% on the daily
closed-equity curve; ≥6 active assets; max asset share of positive PnL ≤ 40%.

Mandatory gates for the selected candidate:

- **DSR (decision gate):** Deflated Sharpe probability ≥ 0.95 with N = number of valid
  evaluated configurations (≤ 8).
- **Heritage DSR (report-only):** the same probability recomputed with N = 6,032
  (5,832 + 192 + 8 — every configuration ever evaluated by 005+006+007) and Sharpe
  variance across the union of published per-configuration Sharpes. Never a gate;
  reported for transparency.
- **Temporal robustness (replaces OOS):** annualized fold Sharpe > 0 in ≥ 7 of 11
  calendar half-year folds (2021H1 … 2026H1, boundaries at Jan‑01/Jul‑01 00:00 UTC)
  **and** median fold Sharpe > 0.
- SPA consistent p ≤ 0.05 (Hansen stationary bootstrap, screened; seed above).
- Holm-adjusted p ≤ 0.05.
- Circular block-bootstrap net-return CI lower bound > 0 (seed above, B=2000, block
  length round(n^(1/3))) on the DECIDE trade sequence.
- ≥60% profitable parameter neighbors (neighbors differ in exactly one frozen grid axis
  as defined above; denominator = valid evaluated neighbors).
- Stress scenarios fees×2, slippage×3, funding magnitude×2, funding sign-flip×2 — each
  must keep aggregate net > 0.
- Concentration/coverage as in eligibility. Long/short directional gate does not apply
  (side = long everywhere).

Ordering (pre-registered tie-break, unchanged): eligible first, then median fold Sharpe
desc, aggregate Sharpe desc, net return desc, drawdown closest to zero, key asc. Rank 1
full passer wins deterministically.

## Decision rule

Exactly one passing configuration ⇒ `SELECT` with full statistics and a forward
monitoring plan on the reserve. Zero passing configurations ⇒ final verdict
`NO_SELECTION`, and **the altcoin multi-timeframe trend line is closed permanently**;
this closure is recorded in the run artifacts and handoff documentation. No successor
protocol may re-open selection on any window overlapping 2021‑01…2026‑06 (2021–2023 is
additionally burned by 005, 2024 by 006).

## Prohibitions

Identical to ALT-MULTITF-005/006: no changes to engine/grid/windows/universe/costs/
seeds/gates/correction/bootstrap to obtain a winner; no analysis of the monitor reserve
under any circumstances; smoke runs are not sweeps; stop on hash/grid-count mismatch;
artifacts must record exact SHA-256 of every input, commands, counts, resume checks and
the deterministic decision.

Artifacts directory: `reports/artifacts/altcoin-multitf-007/`.
