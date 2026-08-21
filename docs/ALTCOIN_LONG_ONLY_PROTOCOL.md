# ALT-LOMOM-002-A — frozen long-only altcoin momentum protocol

## Status and provenance

- **Protocol ID:** `ALT-LOMOM-002-A`
- **Status:** frozen documentation; Phase 2 complete; implementation not started.
- **Frozen on:** 2026-08-21, before implementation or any new calculation.
- **Evidence class:** exploratory fixed-basket evidence with known survivorship/selection bias. Universe-level inference is prohibited.
- **Provenance:** this adaptive hypothesis was formulated after the failed `ALT-XSMOM-001-B` post-mortem. It is a new hypothesis, not a repair, continuation, or retuning of the rejected strategy.

The old protocol, its grid, verdict, and sealed HOLDOUT remain unchanged. No result under this protocol may rehabilitate `ALT-XSMOM-001-B`.

## Frozen universe and eligibility

The universe is exactly:

`ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`, `ADAUSDT`, `DOGEUSDT`, `LINKUSDT`, `LTCUSDT`, `AVAXUSDT`, `DOTUSDT`.

The basket is fixed and may not be changed using prior symbol attribution. This knowingly retains survivorship and selection bias.

A symbol is eligible at a rebalance only if all required closed 1h bars, quote-volume inputs, and funding observations needed by the causal calculation are present. At least five symbols must be eligible; otherwise the portfolio remains entirely in cash until the next scheduled rebalance. Missing funding must never be imputed as zero.

## Single frozen candidate

### Signal

For every eligible symbol, calculate trailing 30-calendar-day close-to-close momentum using only fully closed 1h bars available at the decision timestamp. Rank descending. No data from the decision bar after the decision timestamp may be used.

### Portfolio construction

- Hold only the top four eligible symbols.
- Pre-scaling target weight is exactly 25% per selected symbol.
- No short positions.
- No individual inverse-volatility weighting.
- Unallocated exposure remains cash.

### Rebalance and execution

- Rebalance every seven calendar days at one fixed UTC timestamp established by implementation before its first run.
- Execute no earlier than the open of the next available 1h bar.
- Hold positions unchanged between scheduled rebalances.
- No intraperiod rank-based replacement or discretionary rebalance is allowed.

### Portfolio-level volatility scaling

Use only causal trailing 30-calendar-day realised volatility of the portfolio to target 20% annualised volatility. Apply one common gross multiplier bounded to `[0, 1]`; residual capital remains cash. Scaling may reduce but never increase the four 25% weights, so the per-symbol cap is mechanically preserved.

The exact annualisation and warm-up formula must be specified in code tests before the first strategy calculation and cannot then change.

## Costs, funding, and risk constraints

- Realistic cost: 0.12% round trip applied to actual turnover.
- Stress cost: 0.20% round trip applied to actual turnover.
- Funding: actual timestamp and side; missing required funding makes the observation ineligible, never zero.
- Gross exposure: at most 1.0.
- Net exposure: within `[0, 1]`.
- Per-symbol exposure: at most 25%.
- Participation: at most 1% of trailing causal hourly quote volume.
- Zero short exposure.

## No-search rule

This protocol contains exactly one candidate. Alternative momentum horizons, rebalance frequencies, top-k values, weighting schemes, volatility targets, basket members, and cost assumptions may not be searched. Any such change requires a new protocol ID and new prospective calendar.

## Calendar and contamination policy

All timestamps before `2026-01-01T00:00:00Z` have already influenced hypothesis generation and are **DEVELOPMENT/TRAIN**, not clean out-of-sample evidence.

The old `ALT-XSMOM-001-B` HOLDOUT beginning `2026-01-01T00:00:00Z` remains sealed for that protocol and cannot be reinterpreted as its TEST. Data from 2026 before the prospective freeze boundary cannot count as prospective evidence for this adaptive hypothesis.

Frozen calendar for `ALT-LOMOM-002-A`:

- **DEVELOPMENT/TRAIN:** timestamps `< 2026-01-01T00:00:00Z` only.
- **Prospective VALIDATION:** `[2026-09-01T00:00:00Z, 2027-09-01T00:00:00Z)`.
- **New sealed HOLDOUT:** `[2027-09-01T00:00:00Z, +∞)`.

Phase 3 may access only DEVELOPMENT/TRAIN. Phase 4 is forbidden before prospective VALIDATION is complete and the owner grants separate permission. The new HOLDOUT remains sealed until a separate immutable opening memo and explicit owner permission.

## Mechanical prospective VALIDATION gate

All conditions must pass:

1. At least 252 daily-equivalent observations and at least 50 scheduled rebalance decisions.
2. Net annualised Sharpe at realistic costs is at least 0.75.
3. The lower bound of the predeclared 95% block-bootstrap Sharpe interval is greater than zero.
4. Compounded net return under 0.20% stress costs is positive.
5. Maximum drawdown is no worse than −30%.
6. No symbol contributes more than 40% of positive total net PnL.
7. At least three of four calendar quarters have positive net return.
8. There are zero per-symbol, gross-exposure, execution-causality, and data-boundary violations.

Failure of any condition means **FAIL / STOP** without retuning. Controls and diagnostics may explain but never override the verdict.

Before implementation, Phase 3 must freeze the exact bootstrap block length, daily-equivalent aggregation, annualisation convention, volatility warm-up, fixed UTC rebalance timestamp, and participation sizing mechanics in tests. These are implementation details, not tunable strategy parameters.

## Current gate

Phase 2 is complete. Stop before implementation. Phase 3 requires a separate explicit owner decision; this document does not authorize code, data download, backtesting, prospective VALIDATION access, paper trading, or live trading.
