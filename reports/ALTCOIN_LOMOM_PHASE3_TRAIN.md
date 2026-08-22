# ALT-LOMOM-002-A — Phase 3 DEVELOPMENT/TRAIN

**Evidence:** exploratory fixed-basket evidence with survivorship/selection bias. Fixed basket knowingly retains survivorship/selection bias.

**Scope:** only `2020-05-11T00:00:00Z` to `< 2026-01-01T00:00:00Z`. No 2026+ data, prospective VALIDATION, sealed HOLDOUT, grid search, paper or live trading was accessed.

## Frozen implementation

Monday 00:00 UTC rebalance; 30-day momentum; top 4 at 25% before one common 20% volatility-target multiplier; 30 complete UTC daily shadow-portfolio returns with sqrt(365) annualisation; 30-day bootstrap blocks; 1% prior-hour quote-volume participation cap; 0.12% realistic and 0.20% stress turnover costs.

## TRAIN result

- realistic net Sharpe: `1.1508`
- realistic compounded return: `270.37%`
- stress compounded return: `254.18%`
- max drawdown: `-28.00%`
- bootstrap Sharpe CI95: `[0.2308; 2.0609]`
- observations / scheduled rebalances: `2060 / 295`
- maximum symbol share of positive net PnL: `15.23%`
- constraint/data-boundary violations: `0`
- ledger reconciliation: **PASS**

## Mechanical TRAIN diagnostic

**PASS**. This is contaminated DEVELOPMENT/TRAIN evidence, not prospective confirmation. It cannot by itself authorize Phase 4, paper trading, or live trading.

Checks: `{"at_least_three_positive_quarters": true, "bootstrap_lower_above_zero": true, "max_drawdown_no_worse_than_minus_30pct": true, "observations_at_least_252": true, "realistic_sharpe_at_least_0_75": true, "rebalances_at_least_50": true, "stress_compounded_positive": true, "symbol_positive_pnl_share_at_most_40pct": true, "zero_violations": true}`.

Artifacts: `config.json`, `input-hashes.json`, `ledger-train.csv`, and `train-result.json` in `reports/altcoin-lomom-phase3/`.
