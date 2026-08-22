# Phase 5 — frozen 1h final pre-TEST falsification

Verdict: **PASS**.

TEST с `2025-01-01` не загружался, не анализировался и не открывался.

## Criteria

| Criterion | Result |
|---|---:|
| `positive_without_top_5` | PASS |
| `positive_without_best_year` | PASS |
| `positive_without_best_90d_cluster` | PASS |
| `positive_at_0_16pct_cost` | PASS |
| `rolling_12m_positive_share_over_50pct` | PASS |
| `all_leave_one_causal_regime_out_positive` | PASS |
| `combined_execution_stress_non_negative` | PASS |

## Baseline

- Trades: 185
- Total: `+16.387R`
- Without top-5: `+9.808R`
- Without best year (2024): `+7.294R`
- Rolling 12m positive share: `78.4%`

## Continuous clusters

- Without best 30d cluster: `+10.556R`.
- Without best 60d cluster: `+9.638R`.
- Without best 90d cluster: `+8.330R`.

## Execution

- `cost_0_16pct`: 185 trades, `+12.210R`.
- `entry_delay_1_extra_bar`: 185 trades, `-2.358R`.
- `missed_5pct`: 178 trades, `+8.500R`.
- `missed_10pct`: 158 trades, `+13.079R`.
- `missed_20pct`: 160 trades, `+24.493R`.
- `adverse_slippage`: 185 trades, `+12.210R`.
- `funding_x2`: 185 trades, `+15.164R`.
- `combined`: 158 trades, `+4.792R`.

## Interpretation

Phase 5 is a descriptive full pre-TEST falsification, not a new OOS estimate. No failed scenario may be discarded, regimes are not trading filters, and the verdict cannot be changed after observing results.
