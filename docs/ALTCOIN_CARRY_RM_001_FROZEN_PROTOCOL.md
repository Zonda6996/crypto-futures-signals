# ALTCOIN_CARRY_RM_001 frozen protocol (H-CARRY-RM "risk-managed funding carry")

Status: **frozen before any window analysis**. Committed to git prior to reading any
market content under its windows; the commit timestamp is the freeze proof. This
protocol reuses the ALTCOIN_CARRY_001 simulator contract unchanged and adds one
mechanical risk overlay on top of it. No gate, cost, seed or criterion may be weakened
after this commit.

## Hypothesis

The CARRY-001 diagnostics (published, `ALTCOIN_CARRY_001_HANDOFF.md`) showed a gross
carry premium that survives real costs but fails deployability through deep equity
drawdowns driven by single crash days (−20.2% on 2021-04-17 for core A; −29.2% on
2022-10-31 for core B), while the statistically cleanest configuration missed the
eligibility drawdown ceiling by 4.2 points. H-CARRY-RM states: **scaling the carry
portfolio's gross exposure down as its own realized drawdown deepens converts the same
premium into a tradable profile** without destroying net expectancy or temporal
consistency.

## Declared limitation (cumulative search and informed design)

- Cumulative trials grow to **N = 6,052** (6,044 + the eight new configurations);
  heritage DSR at this N is report-only.
- The two carry cores below are chosen from published CARRY-001 results (the only two
  configurations that passed the full statistical stack there); the overlay is designed
  after observing those crash-day losses. Both facts are disclosed as design inputs.
- Two reference rows (the bare cores without overlay) are re-emitted inside this run
  solely as comparability anchors; they reproduce already-counted CARRY-001 trials,
  add no new information and are **excluded from N, gates and ordering**.

## Data contract

Identical to `ALTCOIN_CARRY_001_FROZEN_PROTOCOL.md` verbatim: ten frozen universe
perpetuals, supplement v2 normalized funding + 1d closes, inherited archive hashes, no
downloads, monitor reserve never read. DECIDE window unchanged:
`2021-01-01T00:00:00Z .. 2026-06-30T23:59:59Z`.

## Simulation contract

Everything in the CARRY-001 simulation contract applies verbatim (signal definition,
ranking with ascending tie-break, ±1/(2K) targets, drift between rebalances, costs on
traded notional, day-skip rule, lexicographic stability). The single addition:

**Drawdown de-risking overlay.** At the close of each UTC day `d`, after applying that
day's growth and costs, compute the strategy's drawdown from its running peak equity:
`dd(d) = eq(d)/peak(d) − 1 ≤ 0`. The exposure multiplier applied to positions
established at close `d` (governing day `d+1`) is:

```
m(dd) = 1                                  if dd ≥ start
m(dd) = max(floor, 1 − (dd − start)/(stop − start))   otherwise
floor = 0
```

i.e. linear de-risking from full size at `start` to fully flat at `stop`. All position
fractions are scaled by `m` equally (dollar-neutrality preserved); any resulting
position change counts as traded notional and pays standard costs at that rebalance.
On non-rebalancing days existing fractions are additionally rescaled to the current
multiplier with corresponding turnover costs — the overlay must act immediately, not
only on rebalance dates. The multiplier used on day `d+1` depends only on information
through close `d` (causal).

## Frozen grid — exactly 8 configurations

Carry cores (from published CARRY-001 diagnostics):

```
core A : lookback_days = 3, k_per_side = 3, rebal_days = 1
core B : lookback_days = 7, k_per_side = 2, rebal_days = 1
```

Overlay parameters:

```
dd_start : {0.05, 0.10}
dd_stop  : {0.15, 0.20}
```

Count check: 2 × 2 × 2 = **8**, constraint `start < stop` holds everywhere. Neighbor
axes are exactly: core (A/B), dd_start, dd_stop — every configuration has exactly three
single-axis neighbors. Reference rows (bare A, bare B) sit outside the grid.

## Costs (dual-track, fixed ex ante)

Unchanged from CARRY-001: primary fee 4 bps + slippage 2 bps per unit traded notional;
maker 2 + 1 report-only track; stress scenarios fees×2, slippage×3, funding magnitude
×0.5, funding sign-flip — each must keep aggregate net > 0.

## Seeds

Sweep/ordering `20260921`; bootstrap `20260922`; SPA `20260923`.

## Statistical contract and gates

Verbatim CARRY-001 gate stack, no weakening:

- Eligibility: ≥100 aggregate symbol-episodes; net > 0; annualized Sharpe > 0.5;
  max DD ≥ −25%; ≥6 active assets; max asset share of positive PnL ≤ 40%.
- **DSR decision gate ≥ 0.95** with N = valid evaluated configurations (≤ 8).
- Heritage DSR at N = 6,052 — report-only.
- Temporal robustness: annualized fold Sharpe > 0 in ≥ 7 of 11 calendar half-year folds
  (boundaries identical to CARRY-001) AND median fold Sharpe > 0.
- SPA consistent p ≤ 0.05 (panel over the eight grid rows); Holm-adjusted p ≤ 0.05;
  block-bootstrap mean-return CI lower bound > 0 (B=2000, block round(n^(1/3)),
  seed above) on DECIDE daily returns.
- ≥60% profitable parameter neighbours (denominator = valid evaluated neighbours).
- Concentration/coverage as in eligibility.

Ordering: eligible first, median fold Sharpe desc, aggregate Sharpe desc, net return
desc, drawdown closest to zero, key asc; rank-1 full passer wins.

## Decision rule

Exactly one passing configuration ⇒ `SELECT`. Zero ⇒ `NO_SELECTION` meaning
**risk-managed carry is unproven as deployable**. Either way H-CARRY-SL (explicit
per-position stops / take-profits with partial profit-taking) remains a separate
pre-registered candidate family for a future freeze, as does H-MR (daily mean
reversion). Re-tuning any family on DECIDE-overlapping windows stays prohibited.

## Prohibitions

No changes to engine/grid/windows/universe/costs/seeds/gates/correction/bootstrap to
obtain a winner; no analysis of the monitor reserve; smoke runs are not sweeps; stop on
hash/grid-count mismatch; artifacts record input hashes, commands, counts, resume checks
and the deterministic decision.

Artifacts directory: `reports/artifacts/altcoin-carry-rm-001/`.
