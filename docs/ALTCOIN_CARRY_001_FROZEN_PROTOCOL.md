# ALTCOIN_CARRY_001 frozen protocol (H-CARRY "cross-sectional funding carry")

Status: **frozen before any window analysis**. Committed to git prior to reading any
market content under its windows; the commit timestamp is the freeze proof. This is a
NEW hypothesis family, independent of the closed ALT-MULTITF trend line; it reuses the
established statistical gate stack unchanged in strength and the immutable input
archives. No gate, cost, seed or criterion may be weakened after this commit.

## Hypothesis

Cross-sectional funding-rate carry on USDT perpetuals: symbols whose trailing funding is
high should be shorted (shorts collect positive funding), symbols whose trailing funding
is low/negative should be longed (longs collect negative funding). The edge, if any, is
a positioning-premium collected through time, not directional price prediction. The
portfolio is dollar-neutral by construction and its costs scale with a slow rebalance
cadence, addressing the two failure modes documented for the trend family (directional
drawdowns; turnover-proportional cost walls).

## Declared limitation (cumulative search)

This protocol follows 005 (5,832 configurations), 006 (192) and 007 (8) on overlapping
history. The design below is informed by those published diagnostics; cumulative trials
grow to **N = 6,044** and are priced into a report-only heritage statistic. A
`NO_SELECTION` here means *this hypothesis is unproven*, not that the research program
stops; further families require their own new freezes.

## Data contract

- Universe (unchanged, never reselected): `BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT,
  ADAUSDT, DOGEUSDT, AVAXUSDT, LINKUSDT, DOTUSDT` USDT-margined perpetuals.
- Inputs: exclusively the already-verified archives — supplement v2 normalized layer
  (`altcoin-multitf-006-supplement`) for funding event series and 1d closes; provenance
  hashes inherited verbatim from `ALTCOIN_MULTITF_007_FROZEN_PROTOCOL.md`
  (primary `665ac7b7…83743d`, v1 `a753585a…47bd5b`, v2 `487046fa…0d10c56`).
  No exchangeInfo snapshot is required: the simulator performs fractional notional
  accounting and never emits exchange orders. No download of any kind is required.
- Funding sign convention: when rate > 0 longs pay shorts. A position with signed
  notional fraction `w` therefore receives `−w · rate` per funding event.

## Windows

| Interval | UTC | Role |
| --- | --- | --- |
| Engine span | from earliest acquired history | signal warmup (≤ 7 days; trivially satisfied) |
| DECIDE (single pass) | `2021-01-01T00:00:00Z` .. `2026-06-30T23:59:59Z` | all statistics and the only selection ever performed |
| Monitor reserve | `2026-07-01T00:00:00Z` .. | untouched, never read by this protocol |

## Simulation contract (deterministic)

1. At the close of each UTC day `d`, symbol `i` has a valid signal iff it has both a 1d
   close at `d` and ≥ `lookback` calendar days of funding history ending at `d`. Signal
   `s_i(d)` = arithmetic mean of raw funding rates of all events in
   `[d − lookback + 1 … d]`.
2. If fewer than ten symbols have valid signals, the day is non-rebalancing (existing
   positions persist). Otherwise rank by `s` descending, tie-break symbol ascending;
   SHORT set = top `K`, LONG set = bottom `K`; target weights `±1/(2K)` (gross = 1).
3. Positions are signed notional fractions. Day-by-day, for each day `u`:
   `r_px(u)` = close(u)/close(u−1) − 1 per symbol; portfolio price+funding growth
   `m = 1 + Σ w_i·r_px,i(u) − Σ w_i·F_i(u)` where `F_i(u)` = sum of funding rates of
   events inside day `u`; fractions then drift `w_i ← w_i·(1+r_px,i)/m`.
4. Rebalancing every `rebal` days to freshly computed targets; proportional cost
   `(fee_bps + slippage_bps)/10^4 × Σ|targets − drifted|` is deducted from equity at
   the rebalance; fractions then equal targets.
5. A day with any missing 1d close among the ten symbols is skipped entirely
   (positions frozen); with the verified inputs this case does not occur in DECIDE.
6. All aggregation orders lexicographically stable; non-finite values invalidate the
   configuration. Equity curve starts at 1.0 on the first DECIDE day.

## Frozen grid — exactly 12 configurations

```
lookback_days : {1, 3, 7}
k_per_side    : {2, 3}
rebal_days    : {1, 7}
```

Count check: 3 × 2 × 2 = **12**. Neighbor axes are exactly these three grid axes; every
configuration has up to six single-axis neighbors (two via lookback, one via K, one via
rebal, intersected with the grid).

## Costs (dual-track, fixed ex ante)

- Primary decision track: fee 4 bps + slippage 2 bps per unit of traded notional.
- Secondary report-only track: maker 2 bps + slippage 1 bps. Never a gate.

## Seeds

Sweep/ordering `20260914`; bootstrap `20260915`; SPA `20260916`.

## Statistical contract and gates (no weakening vs 005–007)

Eligibility (per configuration, DECIDE window): ≥100 aggregate symbol-episodes (one
episode = one symbol held across one rebalance interval); net return > 0; annualized
daily Sharpe (√365) > 0.5; max drawdown ≥ −25%; ≥6 active assets; max asset share of
positive PnL ≤ 40%.

Mandatory gates for the selected candidate:

- **DSR (decision gate)** ≥ 0.95 with N = number of valid evaluated configurations.
- **Heritage DSR (report-only)** recomputed at N = 6,044 with Sharpe variance across the
  union of published per-configuration Sharpes of 005 (5,832), 006 (192), 007 (8) and
  the twelve current values.

ERRATUM (committed before any window analysis): the original freeze text named the
variance sources as "published 005/006 Sharpes plus the twelve current values" while
already fixing N = 6,044; the source list omitted 007's eight published Sharpes by
accident of wording. The corrected union (005+006+007+current) matches the frozen
N = 6,044 exactly and changes nothing else. Grid count remains 12; this erratum
predates the first sweep run.
- **Temporal robustness:** annualized fold Sharpe > 0 in ≥ 7 of 11 calendar half-year
  folds (boundaries identical to 007) **and** median fold Sharpe > 0.
- SPA consistent p ≤ 0.05 (screened stationary bootstrap, panel of configuration daily
  return series, NW lag rule as in prior protocols).
- Holm-adjusted p ≤ 0.05.
- Circular block-bootstrap mean-return CI lower bound > 0 (B = 2000, block
  round(n^(1/3)), seed above) on the DECIDE daily return sequence.
- ≥60% profitable parameter neighbours (denominator = valid evaluated neighbours).
- Stress scenarios fees×2, slippage×3, funding magnitude×0.5, funding sign-flip — each
  must keep aggregate net > 0.
- Concentration/coverage as in eligibility.

Ordering (pre-registered tie-break): eligible first, median fold Sharpe desc, aggregate
Sharpe desc, net return desc, drawdown closest to zero, key asc. Rank-1 full passer wins.

## Decision rule

Exactly one passing configuration ⇒ `SELECT`. Zero ⇒ final verdict `NO_SELECTION`
meaning **the H-CARRY hypothesis is unproven on this data**; the research program may
continue with other pre-registered families, but H-CARRY may not be re-tuned or re-run
on any window overlapping DECIDE.

## Prohibitions

No changes to simulator/grid/windows/universe/costs/seeds/gates/correction/bootstrap to
obtain a winner; no analysis of the monitor reserve; smoke runs are not sweeps; stop on
hash/grid-count mismatch; artifacts must record input hashes, commands, counts, resume
checks and the deterministic decision.

Artifacts directory: `reports/artifacts/altcoin-carry-001/`.
