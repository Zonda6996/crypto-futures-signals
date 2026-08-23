# ALTCOIN_CARRY_FINAL_001 frozen protocol (H-CARRY-FINAL "hardened carry")

Status: **frozen before any window analysis**. Committed to git prior to reading any
market content under its windows; the commit timestamp is the freeze proof. This is the
final in-sample hardening pass over the validated carry family: the SL-001 champion
configuration is the fixed base arm, and exactly three orthogonal hardening axes are
tested on top of it. No gate, cost, seed or criterion may be weakened after this commit.

## Hypothesis

The SL-001 champion (core A + atr3 stop + full take 1:1) passes eligibility, SPA and
DSR but fails the Holm multiplicity gate; its residual weaknesses are crash-day beta
(−23% DD came from market-wide legs), equal weighting of assets with wildly different
volatility, and dead low-dispersion periods. H-CARRY-FINAL states: **market-beta
hedging, inverse-volatility weighting and a funding-dispersion deployment gate each
improve the risk-adjusted profile enough to clear the frozen statistical stack** —
without changing the champion's entry/exit machinery.

## Declared limitation

Design informed by all five published protocols; cumulative trials grow to
**N = 6,090** (6,082 + 8 new configurations); heritage DSR at this N is report-only.
This is the last planned in-sample pass over the carry family; further validation is
forward-only (monitor reserve 2026-07…08 and live data).

## Base arm (fixed, from SL-001 published results)

```
core A : lookback_days = 3, k_per_side = 3, rebal_days = 1
stop   : atr3  (3 × Wilder ATR(14) from entry, daily close checks)
take   : f1:1  (full position closed at +1 × dist)
```

Episode mechanics, anti-blowup cap, daily trim, costs and day-skip rules are exactly
`ALTCOIN_CARRY_SL_001_FROZEN_PROTOCOL.md` verbatim. The all-off grid corner
(hedge=off, weights=equal, gate=always) must reproduce the published SL-001 champion
row exactly (regression invariant, tested).

## Hardening axes (frozen definitions)

**H — market-beta hedge {off, on}.** At each day's close, the net market beta of the
book is estimated as the held-weights average of per-symbol trailing betas:
`β_i = cov(r_i, r_btc) / var(r_btc)` over the last 90 daily returns ending at the
previous close (causal; symbols without 90 days of history contribute β=1). The hedge
leg is a BTC-perp position with signed notional `−β_book × gross`, held outside the
episode book (no stops/takes on the hedge; it is resized daily with standard turnover
costs). When the book is flat the hedge is flat.

**W — position weights {equal, inverse-vol}.** Equal: ±1/(2K) as published.
Inverse-vol: per-symbol target magnitude `u_i ∝ 1/σ_i`, where
`σ_i = std of the last 30 daily returns of symbol i` ending at the previous close
(causal), normalized so that the gross exposure of the K+K book equals 1.0. Episode
stop/take distances are unchanged (ATR-based, entry-day).

**G — deployment gate {always, dispersion-gated}.** Always: no restriction.
Dispersion-gated: define `disp(d)` = cross-sectional standard deviation of the ten
current funding signals (the trailing-mean funding values used for ranking). The gate
is OPEN when `disp(d) ≥ median(disp)` over the trailing 180 calendar days ending at
the previous close (causal). While the gate is CLOSED no new episodes may open;
existing episodes continue under normal rules (stops, takes, rank-drops, daily trims
all active). The gate never forces exits.

## Frozen grid — exactly 8 configurations

```
hedge   : {off, on}
weights : {equal, inverse-vol}
gate    : {always, dispersion-gated}
```

Count check 2×2×2 = **8**, all on the fixed base arm. Neighbour axes are exactly these
three; every configuration has exactly three single-axis neighbours.

References outside gates (3 rows): the SL-001 RISK arm (A+atr3+p1:2+BU), bare core A
(no stop/take), bare core B. The SL-001 champion corner sits inside the grid as the
regression anchor (its exact reproduction is a hard invariant). References are excluded
from N, gates and ordering.

ERRATUM (committed before any window analysis): the original freeze text said
"4 rows" of references and contained a garbled seeds line. Corrected: three reference
rows (the champion anchor is in-grid, not a reference), and the frozen seeds are
sweep `20261005`, bootstrap `20261006`, SPA `20261007`. Nothing else changes; grid
count remains 8; this erratum predates the first sweep run.

## Costs, seeds, windows

Unchanged: primary fee 4 bps + slippage 2 bps per unit traded notional (hedge leg
included); maker 2+1 report-only; DECIDE window `2021-01-01T00:00:00Z ..
2026-06-30T23:59:59Z`; monitor reserve never read. Seeds: sweep `20261005`,
bootstrap `20260906`+1 ⇒ bootstrap `20261006`, SPA `20261007`.

## Statistical contract and gates

Verbatim SL-001 stack: eligibility (≥100 episodes, net > 0, Sharpe > 0.5, DD ≥ −25%,
≥6 assets, concentration ≤40%); DSR decision gate ≥0.95 at N = valid configurations;
heritage DSR at N = 6,090 report-only; temporal robustness ≥7/11 half-years positive
AND median fold Sharpe > 0; SPA ≤ 0.05; Holm ≤ 0.05; block-bootstrap CI lower > 0;
≥60% profitable neighbours; stress fees×2 / slippage×3 / funding-half / funding-flip
each net > 0 (stress applies to the full configured book including hedge); ordering:
eligible first, median fold Sharpe desc, aggregate Sharpe desc, net desc, DD closest to
zero, key asc; rank-1 full passer wins.

## Decision rule

Exactly one passer ⇒ `SELECT` (the hardened champion becomes the TIDAL SAFE-mode
candidate). Zero ⇒ `NO_SELECTION` ("hardened carry unproven; carry family in-sample
work concluded"). Either way, further carry tuning on DECIDE-overlapping windows is
prohibited; validation continues forward-only. D6/OI integration remains external
(owner's line, population question unresolved) and is out of scope here.

## Prohibitions

Standard set: no post-hoc changes of engine/grid/windows/costs/seeds/gates; no monitor
reserve analysis; smoke runs are not sweeps; stop on hash/grid-count mismatch; artifacts
record hashes, commands, counts, resume checks and the deterministic decision.

Artifacts directory: `reports/artifacts/altcoin-carry-final-001/`.
