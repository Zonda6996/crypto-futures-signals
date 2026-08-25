# ALTCOIN_XS_001 frozen protocol (H-XS "cross-sectional momentum")

Status: **frozen before any window analysis**. Committed to git prior to reading any
market content under its windows; the commit timestamp is the freeze proof. New
hypothesis family: cross-sectional momentum on the frozen universe — rank the ten
perps by trailing price return, long the strongest / short the weakest, market-neutral.
No gate, cost, seed or criterion may be weakened after this commit.

## Hypothesis

Relative strength persists: symbols that outperformed the universe over the trailing
window tend to keep outperforming over the next days (cross-sectional momentum), and
symbols that lagged keep lagging. Unlike the closed price-flush MR line (absolute
moves) and the dead trend line (per-symbol SMA), the signal is purely RELATIVE — the
market direction is hedged away by construction.

## Declared limitation

Design informed by all seven published protocols of this repo and by the external
SMC-Research-Engine corpus (D-lead side anti-phase; momentum-crash caveat). Cumulative
trials grow to **N = 6,134** (6,122 + 12); heritage DSR at this N is report-only.

## Data contract

- Universe (unchanged, never reselected): the ten frozen USDT-M perpetuals.
- Inputs: daily closes + funding events from the verified v2 normalized layer
  (identical hashes to all prior protocols). **No downloads.**
- DECIDE window: `2021-01-01T00:00:00Z .. 2026-06-30T23:59:59Z`; monitor reserve
  never read.

## Simulation contract

Identical to `ALTCOIN_CARRY_001_FROZEN_PROTOCOL.md` (dollar-neutral fractions,
daily drift, funding accrual `−Σ w·F`, proportional costs on turnover, day-skip rule,
lexicographic stability) with one change — the signal:

1. At the close of day `d`: momentum of symbol `i` =
   `close_i(d) / close_i(d − window) − 1` (uses data through close `d`, causal).
2. Rank descending, tie-break symbol ascending. LONG set = top `K`, SHORT set =
   bottom `K`. All ten momenta are always valid inside DECIDE (history since 2020).
3. Targets `±1/(2K)` (gross = 1) applied on rebalance days (`index % rebal == 0`);
   positions drift between rebalances; funding accrues daily to the holder.

## Frozen grid — exactly 12 configurations

```
window_days  : {3, 7, 14}
k_per_side   : {2, 3}
rebal_days   : {1, 7}
```

Count check 3 × 2 × 2 = **12**. Neighbour axes: window (2 neighbours), K (1),
rebal (1) → up to four single-axis neighbours per configuration.

References outside gates (2 rows): buy-and-hold equal-weight basket and buy-and-hold
BTC over DECIDE — market anchors, excluded from N, gates and ordering.

## Costs (dual-track, fixed ex ante)

Primary: fee 4 bps + slippage 2 bps per unit of traded notional. Maker 2+1
report-only. Stress: fees×2, slippage×3, funding magnitude×0.5, funding sign-flip —
each must keep aggregate net > 0.

## Seeds

Sweep `20261019`; bootstrap `20261020`; SPA `20261021`.

## Statistical contract and gates

Verbatim program stack: eligibility (≥100 symbol-episodes, net > 0, annualized
Sharpe > 0.5, max DD ≥ −25%, ≥6 active assets, max asset share of positive PnL ≤ 40%);
DSR decision gate ≥ 0.95 at N = valid configurations; heritage DSR at N = 6,134
report-only; temporal robustness ≥ 7/11 calendar half-year folds positive AND median
fold Sharpe > 0; SPA ≤ 0.05; Holm ≤ 0.05; block-bootstrap CI lower > 0; ≥60%
profitable neighbours; concentration/coverage as eligibility. Ordering: eligible
first, median fold Sharpe desc, aggregate Sharpe desc, net desc, DD closest to zero,
key asc; rank-1 full passer wins.

## Decision rule

Exactly one passer ⇒ `SELECT`. Zero ⇒ `NO_SELECTION` ("cross-sectional momentum
unproven on this universe"). Aftermath: momentum is NOT re-tuned on DECIDE-overlapping
windows; a negative result closes the XS family. Interaction with the live carry
SELECT and the external D6 line is portfolio-layer work (separate freeze), not a
rescue path for this protocol.

## Prohibitions

Standard set: no post-hoc changes of engine/grid/windows/costs/seeds/gates; no
monitor reserve analysis; smoke runs are not sweeps; stop on hash/grid-count mismatch;
artifacts record hashes, commands, counts, resume checks and the deterministic
decision.

Artifacts directory: `reports/artifacts/altcoin-xs-001/`.
