# ALTCOIN_MR_TF_001 frozen protocol (H-MR "mean reversion after sharp bars, multi-TF")

Status: **frozen before any window analysis**. Committed to git prior to reading any
market content under its windows; the commit timestamp is the freeze proof. New
hypothesis family: event-driven mean reversion on sharp single-bar moves, tested across
four signal timeframes with a self-normalising trigger. No gate, cost, seed or criterion
may be weakened after this commit.

## Hypothesis

A single bar that closes far below (above) its own trailing volatility is followed by a
systematic bounce (fade) — forced-leverage unwinding overshoots fair value. The trigger
is expressed in **volatility units, not percent**, so one rule applies identically on
every timeframe: `return(bar) ≤ −z·σ` for long entries, `≥ +z·σ` for short entries,
where `σ` is the trailing 30-bar standard deviation of that timeframe's returns
(causal, ending at the previous bar).

## Declared limitation

Design informed by all six published protocols of this repo and by the owner's external
SMC-Research-Engine findings (D-lead side anti-phase hint; D6 lesson that tight
take-profits can kill unconfirmed edges — hence exit geometry is an axis, not an
assumption). Cumulative trials grow to **N = 6,122** (6,090 + 32); heritage DSR at this
N is report-only. Timeframe pack 2 (M45/M30/M15/M5) is deliberately deferred until this
freeze resolves; local zone context is out of scope until a stable base exists.

## Data contract

- Universe (unchanged, never reselected): the ten frozen USDT-M perpetuals.
- Bars: normalized v2 layer timeframes **1d, 2h, 4h, 1h** (already aggregated from the
  5m base at archive build time) plus funding events. **No downloads.**
- DECIDE window: `2021-01-01T00:00:00Z .. 2026-06-30T23:59:59Z` in each timeframe's
  own bars; monitor reserve never read.

## Trade mechanics (deterministic)

1. At the close of bar `t`, `σ_t` = std of the last 30 returns of that timeframe
   ending at bar `t−1` (causal). Long signal: `ret(t) ≤ −z·σ_t`; short signal:
   `ret(t) ≥ +z·σ_t`.
2. Entry at close of bar `t`. One open trade per symbol; while a symbol's trade is
   open its new signals are skipped.
3. Exit, per the frozen exit axis:
   - `time3`: close of bar `t + N`, where `N` = 3 days expressed in the timeframe's
     bars (1d→3, 2h→36, 4h→18, 1h→72);
   - `tp11`: stop at `entry −/+ 2×ATR14`, take-profit at `entry ±/− 2×ATR14`
     (reward:risk 1:1; ATR14 = Wilder ATR on the same timeframe, entry-bar value),
     checked on every close until one fires; no time limit.
4. Trade net return (fraction of notional): `side·(exit−entry)/entry − 12 bps
   (4 fee + 2 slippage per fill, two fills) − side·Σ funding rates over the holding
   period` (long pays positive funding, short receives).
5. Notional per trade: 10,000 (initial equity unit); trades pool across symbols into
   the daily closed-equity curve; portfolio denominator 100,000 as in all prior
   protocols.

## Frozen grid — exactly 32 configurations

```
signal_tf : {1d, 2h, 4h, 1h}
z         : {2.0, 3.0}
side      : {long, both}        # both = long after drops AND short after pumps
exit      : {time3, tp11}
```

Count check: 4 × 2 × 2 × 2 = **32**. Neighbour axes: signal_tf, z, side, exit
(single-axis moves inside the grid).

References outside gates (2 rows): buy-and-hold of the equal-weight ten-symbol basket
and buy-and-hold BTC over DECIDE — market context anchors, excluded from N, gates and
ordering.

## Costs, seeds, windows

Primary track 4 bps fee + 2 bps slippage per fill (12 bps round trip); maker 2+1
report-only. Seeds: sweep `20261012`, bootstrap `20261013`, SPA `20261014`.

## Statistical contract and gates

Verbatim program stack: eligibility (≥100 trades, net > 0, annualized daily Sharpe
> 0.5, max DD ≥ −25%, ≥6 active assets, max asset share of positive PnL ≤ 40%);
DSR decision gate ≥ 0.95 at N = valid configurations; heritage DSR at N = 6,122
report-only; temporal robustness ≥ 7/11 calendar half-year folds positive AND median
fold Sharpe > 0 (boundaries identical to prior protocols); SPA ≤ 0.05; Holm ≤ 0.05;
block-bootstrap CI lower > 0 (B=2000, block round(n^(1/3))); ≥60% profitable
neighbours; stress fees×2 / slippage×3 / funding-half / funding-flip each keeps
aggregate net > 0. Ordering: eligible first, median fold Sharpe desc, aggregate Sharpe
desc, net desc, DD closest to zero, key asc; rank-1 full passer wins.

## Decision rule

Exactly one passer ⇒ `SELECT`. Zero ⇒ `NO_SELECTION` ("price-flush mean reversion
unproven at tested timeframes"). Aftermath either way: timeframe pack 2 (M45/M30/M15/M5)
and exit-geometry round 2 require their own freeze; SAFE/RISK product modes are
assembled post-hoc from published arms only. D6/OI remains external (owner's line).

## Prohibitions

Standard set: no post-hoc changes of engine/grid/windows/costs/seeds/gates; no monitor
reserve analysis; smoke runs are not sweeps; stop on hash/grid-count mismatch; artifacts
record hashes, commands, counts, resume checks and the deterministic decision.

Artifacts directory: `reports/artifacts/altcoin-mr-tf-001/`.
