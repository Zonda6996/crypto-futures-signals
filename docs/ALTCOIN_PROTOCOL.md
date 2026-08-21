# ALTCOIN Phase A protocol — frozen preregistration

**Protocol ID:** `ALT-XSMOM-001-A`  
**Frozen:** 21 August 2026  
**Status:** frozen for Phase A (data availability and survivorship audit only)

## Governance and scope

This is an independent experiment. The rejected ETHUSDT strategy and its one-time 2025 TEST are archived as `FAIL`; they must not be rerun, retuned, or used to choose this protocol. Phase A may inspect metadata and market-data availability only. It must not calculate momentum signals, returns, PnL, or select a strategy.

The research venue is Binance USD-M perpetual futures. Any later deployment on BingX requires a separate contract-mapping, fee, funding, liquidity, short-availability, order-behaviour, and fill audit. Binance results are not presumed portable.

The unit of evaluation is one cross-sectional long/short portfolio, not the best coin selected after the fact.

## Sealed calendar

- All Phase A reads and requests must satisfy `timestamp < 2026-01-01T00:00:00Z`.
- The future HOLDOUT is `[2026-01-01T00:00:00Z, +∞)` and is sealed.
- No HOLDOUT metadata, roster, bars, funding, open interest, membership, or derived artifact may be requested, cached, read, or analysed.
- Opening requires a later immutable memo, frozen commit and hashes, one command, one-time sentinel, and exact owner permission.
- TRAIN and VALIDATION must end by `2025-12-31T23:59:59.999Z`. Exact boundaries will be frozen after Phase A, before any return-based computation, based only on the available pre-HOLDOUT history. They may not be chosen from performance.

## Point-in-time universe

At each future rebalance timestamp, rank eligible Binance USD-M **perpetual** contracts by trailing 30-calendar-day quote/dollar volume using observations strictly before the decision timestamp. Select the top 30.

Eligibility is deterministic:

1. Contract is onboarded and actually tradable by the decision timestamp, and has not reached its delist time.
2. At least 90 calendar days have elapsed since onboarding.
3. At least 95% of expected hourly bars exist in the trailing 30-day ranking window.
4. Quote volume is summed only from those trailing observations; no current roster, current market cap, future volume, or backfilled membership is allowed.
5. Exclude stablecoin bases, leveraged-token bases, wrapped/pegged duplicates, delivery contracts, and duplicate exposure under an explicit versioned exclusion table. Initial objective classes are:
   - stablecoin bases: USDT, USDC, BUSD, TUSD, FDUSD, DAI, USDP, USDE;
   - leveraged suffixes: `UP`, `DOWN`, `BULL`, `BEAR`;
   - wrapped/pegged duplicates: WBTC, BTCB, WETH;
   - duplicate base exposure: retain the eligible USDT-quoted perpetual with the greatest trailing quote volume, then lexicographically smallest symbol.
6. Ties are resolved by descending trailing quote volume, earlier onboard timestamp, then lexicographic symbol.
7. New listings enter only after satisfying age and coverage. Delisted contracts remain in the registry and data through their last truly tradable timestamp. Token migrations and renames remain separate records linked by an event table; history is never spliced silently.
8. A current exchange roster is never accepted as a historical registry. Historical listings and delistings must be independently recoverable with dated provenance.

Open interest is an availability diagnostic in Phase A, not an eligibility substitute. If a complete point-in-time OI history is unavailable, that limitation is recorded rather than reconstructed from current values.

## Frozen minimal Phase B family (not executable in Phase A)

The primary family is cross-sectional momentum with long and short books. To constrain later multiple testing, the only admissible initial grid is:

- ranking horizons: 7, 14, and 30 calendar days;
- rebalance frequencies: 8h, 12h, and 24h;
- portfolio: equal risk within the top and bottom quintiles of the eligible Top 30, gross exposure 1.0, target net exposure 0;
- beta-neutralisation: one predeclared BTC-beta-neutral variant, estimated only from trailing data;
- volatility scaling: trailing 30-day realised volatility, winsorised by a causal cross-sectional rule;
- execution: no earlier than the next available bar after ranking.

No member of this family is preferred yet. Any addition or change creates a new protocol version and multiple-testing entry.

## Execution and costs for later phases

All inputs must be known before the decision. Rankings use closed bars; orders execute no earlier than the next bar. Missing decision bars postpone execution rather than being filled retrospectively. Delistings use the last executable market observation with a conservative adverse-exit rule to be frozen before Phase B.

Costs are charged on both entry and exit. Later reports must include 0.10% round trip as the provisional base, 0.12% realistic, and 0.20% doubled-cost stress, plus funding at actual timestamps and side. Participation is capped at the lesser of 1% of trailing hourly quote volume and a later predeclared nominal cap. Short availability, minimum notional, tick/step size, and rejected orders are explicit constraints. Missing funding is not zero: affected exposure is excluded or charged a conservative rule frozen before testing.

## Metrics and decision rule for later phases

Primary metric: net annualised portfolio Sharpe based on rebalance-period net returns, with a stationary/block-bootstrap 95% confidence interval. Before Phase B, block length and annualisation convention will be frozen from sampling frequency, not optimised.

A candidate may advance from VALIDATION only if all are true:

- at least 252 daily-equivalent observations and 100 independent rebalance decisions;
- point estimate of net annualised Sharpe is at least 0.75;
- lower 95% block-bootstrap bound is greater than 0;
- result remains positive under 0.20% doubled-cost stress;
- no single coin contributes more than 25% of total net PnL and no single calendar year contributes more than 50%;
- multiple-testing ledger is complete.

Secondary diagnostics cannot change the primary verdict: turnover, max drawdown, concentration, breadth, gross/net exposure, BTC beta, funding drag, capacity, positive-coin share, leave-one-coin/year-out, and regime breakdown.

## Mandatory controls and falsification

Equal-weight eligible-universe return, BTC/ETH beta-matched control, seeded random ranking, one-bar delayed execution, doubled costs, funding perturbation, participation caps, leave-one-coin-out, leave-one-year-out, removal of top contributors, and neighbouring-parameter stability are mandatory. Controls are not alternative candidates.

Every evaluated configuration, failed run, protocol amendment, and diagnostic with selection potential is entered in a multiple-testing ledger. A post-freeze change receives a new hypothesis ID.

## Phase A verdict gate

Phase A reports exactly one verdict:

- `PASS`: historical registry, delistings, data coverage, and point-in-time Top 30 are reproducible without current-survivor filtering;
- `LIMITED`: reproducible for a clearly bounded period/universe, with limitations that narrow inference;
- `STOP`: historical membership or delisted contracts cannot be reconstructed without material survivorship bias.

Phase A must stop after the report. No automatic transition to signal implementation or parameter search is permitted.
