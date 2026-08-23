# ALTCOIN_CARRY_SL_001 frozen protocol (H-CARRY-SL "funding carry with stops & takes")

Status: **frozen before any window analysis**. Committed to git prior to reading any
market content under its windows; the commit timestamp is the freeze proof. The
protocol upgrades the CARRY-001 simulator to episode-based holding (so that per-position
stops and take-profits are well-defined) and tests a pre-registered grid of stop styles
and take rules. No gate, cost, seed or criterion may be weakened after this commit.

## Hypothesis

CARRY-001/RM-001 published diagnostics showed: a gross carry premium surviving costs;
deep single-day adverse moves (−20…−29%) as the deployment blocker; a portfolio-level
de-risking overlay fixes drawdowns but whipsaws concentrated cores. H-CARRY-SL states:
**per-position, rule-based exits (volatility-scaled price stops, funding-flip
invalidation) combined with mechanical take-profits convert the same premium into a
tradable profile** without destroying expectancy or temporal consistency.

## Declared limitation

Design informed by all four published protocols; cumulative trials grow to
**N = 6,082** (6,052 + 30 new configurations); heritage DSR at this N is report-only.
Same-window reuse is priced exclusively through heritage multiplicity; the monitor
reserve stays untouched.

## Data contract

Verbatim CARRY-001. One addition: the episode engine consumes daily **OHLC** from the
same normalized v2 layer (highs/lows required by ATR); no new downloads.

## Episode mechanics (replaces pure target-following)

A position's life is an **episode** with explicit state:

1. **Open:** symbol enters the ranked basket at close `d` (top-`K` = short side,
   bottom-`K` = long side; ranking/tie-break identical to CARRY-001). Entry price =
   close(`d`); stop distance `dist = m · ATR_symbol(d)` for ATR-style stops (see
   formula below), `dist = 0.10 · entry_price` for the fixed benchmark stop.
2. **Daily checks at each subsequent close `t`, in frozen order:** (a) *rank-drop* —
   symbol left its side-set at a re-ranking close → exit; (b) *flip* — signal crossed
   zero against the side → exit; (c) *stop* — long: `close(t) ≤ entry − dist`; short:
   `close(t) ≥ entry + dist` → exit; (d) *take* — favorable move `≥ R·dist` triggers
   the take rule (below).
3. **Exit execution** at close(`t`) price; freed slots are refilled immediately the
   same close from the current ranking (next candidate not already held; full basket
   whenever ten valid signals exist).
4. **Persisting positions** are trimmed back to target weight ±1/(2K) every day — the
   built-in partial profit-taking of the family — with standard turnover costs.
5. **Anti-blowup cap (mandatory hygiene):** if a fraction drifts beyond 2× target,
   trim to target at that close (costs apply). Directly addresses the documented DOGE
   short-drift blowup.
6. Days with fewer than ten valid signals remain non-rebalancing (positions persist);
   exits still evaluate on those days.

## Stop formula

```
TR(t)  = max(High−Low, |High−Close(t−1)|, |Low−Close(t−1)|)
ATR(t) = (13·ATR(t−1) + TR(t)) / 14          # Wilder smoothing, period 14
dist   = m · ATR(entry-day close), m ∈ {2, 3}
```

Stop styles tested: `atr2`, `atr3`, `flip`, `atr2flip` (both conditions active).
Benchmark reference outside the gates: `fixed10` (±10% from entry).

## Take rules (R measured in units of risk: goal = R · dist)

| code | rule |
| --- | --- |
| none | no take beyond the daily trim |
| p1:1+BU | at +1·dist sell half; remainder stop moved to entry (breakeven) |
| p1:1 | at +1·dist sell half; remainder keeps original stop |
| f1:1 | at +1·dist close the whole position |
| p1:1.5+BU / p1:1.5 / f1:1.5 | same three actions at +1.5·dist |
| p1:2+BU / p1:2 / f1:2 | same three actions at +2·dist |
| p1:3+BU / f1:3 | partial-with-BU and full at +3·dist |

Takes are single-shot per episode. After a partial take the entry price is unchanged;
only the BU variant modifies the remaining stop distance (to zero).

## Frozen grid — exactly 30 configurations

- **Block 1 (stop comparison, take = none):** {atr2, atr3, flip, atr2flip} × cores
  {A(3/3/1), B(7/2/1)} = 8.
- **Block 2 (take comparison, stop = atr3):** 11 non-none takes × 2 cores = 22.

Count check 8 + 22 = **30**. References outside gates: bare cores (must reproduce
CARRY-001 results exactly) and fixed10 per core (4 rows). Block membership affects
REPORTING only; selection happens once, at finalize, over the complete grid.

Reference rows excluded from N, gates and ordering; they anchor comparability and the
no-regression invariant.

## Costs, seeds, windows

Unchanged: primary fee 4 bps + slippage 2 bps on traded notional; maker track
report-only; DECIDE window `2021-01-01 .. 2026-06-30`; monitor reserve never read.
Seeds: sweep `20260928`, bootstrap `20260929`, SPA `20260930`.

## Statistical contract and gates

Verbatim CARRY-001 stack: eligibility (≥100 episodes, net > 0, Sharpe > 0.5,
DD ≥ −25%, ≥6 assets, concentration ≤40%); DSR decision gate ≥0.95 at N = valid
configurations; heritage DSR at N = 6,082 report-only; temporal robustness ≥7/11
half-years positive AND median fold Sharpe > 0 (fold boundaries unchanged); SPA ≤ 0.05;
Holm ≤ 0.05; block-bootstrap CI lower > 0 (B=2000, block round(n^(1/3))); ≥60%
profitable neighbours — neighbour axes: core, stop style, take code (single-axis moves
inside the grid); stress fees×2 / slippage×3 / funding-half / funding-flip each net > 0;
concentration/coverage as eligibility. Ordering: eligible first, median fold Sharpe
desc, aggregate Sharpe desc, net desc, DD closest to zero, key asc; rank-1 full passer
wins.

## Decision rule

Exactly one passer ⇒ `SELECT`; otherwise `NO_SELECTION` ("carry with stops/takes
unproven as deployable"). An interim Block-1 review is a REPORTING checkpoint only
(descriptive tables to the project owner); it performs no selection and cannot change
the grid, gates or seeds. Queued families remain: H-MR, H-XS, H-VOL, portfolio day-brake
variant, cooldown variants.

## Prohibitions

Standard set: no post-hoc changes of engine/grid/windows/costs/seeds/gates; no monitor
reserve analysis; smoke runs are not sweeps; stop on hash/grid-count mismatch; artifacts
record hashes, commands, counts, resume checks and the deterministic decision.

Artifacts directory: `reports/artifacts/altcoin-carry-sl-001/`.
