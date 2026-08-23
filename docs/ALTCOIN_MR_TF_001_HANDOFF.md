# ALTCOIN_MR_TF_001 (H-MR "mean reversion after sharp bars") — final handoff

Status: **protocol executed end-to-end; final verdict `NO_SELECTION`** — 0 of 32
configurations pass eligibility. Freeze proof `db6e4f8`; engine
`research/altcoin_mr_tf_001.py`; z-score self-normalising flush trigger across four
signal timeframes.

## Inputs

No downloads (1d/2h/4h/1h normalized bars + funding all local). DECIDE window
2021-01-01 .. 2026-06-30. Sweep runtime ~38 s for 32 configurations.

## Execution summary

| Stage | Result |
| --- | --- |
| Grid validation | exactly **32** configurations |
| Eligibility | **0 of 32** pass |
| Final verdict | `NO_SELECTION` |

## Key results (net of 12 bps round trip)

Long-only arms (the only ones worth looking at):

| TF | z | exit | trades | net | Sharpe | maxDD | folds+ | SPA |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1d | 2.0 | time3 | 495 | +6.6% | 0.45 | −105.9% | 8/11 | 0.907 |
| 1d | 2.0 | tp11 | 312 | +472.7% | 0.86 | −70.5% | 7/11 | 0.654 |
| 2h | 2.0 | time3 | 3,723 | +2,834.6% | 0.70 | −30.2% | 6/11 | 0.593 |
| 4h | 2.0 | time3 | 2,435 | +1,878.5% | 1.07 | −48.4% | 8/11 | 0.282 |
| 4h | 2.0 | tp11 | 2,373 | +966.4% | 1.18 | −49.5% | 6/11 | 0.253 |
| 1h | 2.0 | time3 | 4,725 | +1,836.9% | 1.11 | −41.2% | 6/11 | 0.354 |

Both-sides arms (short after pumps included): **catastrophically negative everywhere**
(−541% … −2,892%; unbounded short-squeeze losses in fixed-notional accounting).
Daily z=3.0 long arms: negative to flat — the deepest flushes do not bounce reliably.

References: B&H basket +766.7% (DD −80.7%); B&H BTC +102.4% (DD −76.7%).

## Findings

1. **A gross intraday bounce exists**: long-after-flush is net-positive on 1h/2h/4h
   with thousands of trades. But it is a **volatility harvest, not an edge**: SPA
   p ≥ 0.25 everywhere (no configuration distinguishable from noise after multiplicity),
   drawdowns −30…−55% breach the −25% ceiling, and temporal consistency fails (6–8/11).
2. **Shorting pumps is toxic** — the single most one-sided result of the program:
   every both-side arm is destroyed by its short book. Crypto upside momentum after
   pumps is real; fading it is the opposite of a premium.
3. **Tight 1:1 ATR stops chew the bounce**: on 1h, time3 (+1,837%) vs tp11 (−674%) —
   the 2×ATR stop is inside the rebound noise. Replicates the owner's RE15/16 finding
   (reversion movements want wide exits) and the D6 lesson (ARM CANON tight stop KILL).
4. **Daily MR is dead flat** (+6.6% over 5.5 years at z=2.0): the bounce is an
   intraday phenomenon; by daily bars it is already arbitraged into the close.
5. This is the price-only control for the owner's D6 line: on the same universe and
   window, a price-flush trigger alone yields gross-but-unsignifiable bounce income —
   consistent with D6's premise that the *signal lives in the leverage flow (OI)*,
   not in price.

## Consequences

`NO_SELECTION`: price-flush mean reversion is unproven as deployable at 1d/2h/4h/1h
on this universe. Per protocol: TF pack 2 (M45/M30/M15/M5) and exit-geometry round 2
require their own freeze AND a motivating new information set — re-running this grid
with tweaks is prohibited. The gross intraday bounce is recorded as a descriptive fact;
a deployable form would need a confirming context layer (e.g., the external D6/OI
line — owner's call) plus a drawdown solution that the frozen gates currently reject.

## Artifacts (`reports/artifacts/altcoin-mr-tf-001/`)

`input-manifest.json` · `statistics.json` · `eligibility-table.json` ·
`selection-dossier.json` · `verdict-final.json` · `run-metadata.json` ·
`development-metrics.csv` · `sweep-progress.json`

## Reproduction

```bash
uv sync --frozen --group dev
uv run python -m pytest                                             # 125 passed
uv run python -m research.altcoin_mr_tf_001 --validate-grid         # count = 32
uv run python -m research.altcoin_mr_tf_001 --stage sweep   --inputs-root <inputs> --cache-dir <cache>
uv run python -m research.altcoin_mr_tf_001 --stage finalize --inputs-root <inputs> --cache-dir <cache>
```
