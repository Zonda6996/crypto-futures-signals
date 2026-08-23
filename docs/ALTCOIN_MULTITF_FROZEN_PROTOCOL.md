# ALTCOIN_MULTITF_005 frozen protocol

Status: **frozen for the reconstructed Phase 4 baseline**. The unavailable historical Phase 3 outputs are not recreated as empirical observations.

## Data contract

- Universe: `BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, AVAXUSDT, LINKUSDT, DOTUSDT` perpetual futures.
- Native bars: 5m execution; 15m/60m signal; 240m regime. A bar is available only at its close timestamp.
- Development: `2021-01-01T00:00:00Z` through `2023-12-31T23:59:59Z`.
- Evaluation: `2024-01-01T00:00:00Z` through `2024-12-31T23:59:59Z`; sealed until a development-only winner satisfies every mandatory gate.
- Prices/funding/exchange metadata must be immutable local inputs with SHA-256 hashes in the run manifest. Missing required inputs make a configuration invalid; they are never forward-filled across an unknown interval.

## Execution contract

Signals use only bars whose close is at or before decision time and orders fill no earlier than the next 5m bar open. Quantity is floored to step size; executable prices are rounded adversely to tick size. Orders failing finite/positive quantity, min quantity, max quantity, min notional, or available-bar checks are rejected deterministically. Fees are 4 bps per fill and baseline slippage is 2 bps per fill. Funding is charged/credited only at a published funding timestamp while the position was already open; `cashflow = -position_notional * funding_rate`. Returns are normalized by equity immediately before each event.

## Frozen grid

Both families use the Cartesian product below, except invalid `fast >= slow` combinations are excluded before evaluation:

- family: A, B
- signal TF: 15m, 60m
- regime TF: 240m
- fast: 3, 5, 8
- slow: 13, 21, 34
- entry threshold: 0, 0.005, 0.01
- exit threshold: 0, 0.003
- stop ATR: 1.5, 2.0, 2.5
- take ATR: 2.0, 3.0, 4.0
- max holding bars: 12, 24, 48
- side: both

Expected configurations: `2 * 2 * 1 * 3 * 3 * 3 * 2 * 3 * 3 * 3 = 5,832`. This reconstructed grid is authoritative; the earlier approximate 58,140 count cannot be substantiated without the missing historical protocol. Part 2 must stop on any count other than 5,832.

Family A is regime-aligned trend continuation using fast/slow signal averages. Family B is a regime-filtered pullback: deviations from the slow signal average enter toward the regime direction. Exact equations are implemented and tested in `research/altcoin_multitf_phase4.py`.

## Selection and statistical contract

Only development results may be ranked. Invalid configurations are separate from valid configurations with zero trades. Eligibility requires at least 100 aggregate trades, positive net return, Sharpe above 0.5, max drawdown no worse than -25%, at least 6 active assets, and no asset or timeframe contributing over 40% of positive PnL. Deterministic ordering is: eligible, median fold Sharpe, aggregate Sharpe, net return, lower drawdown, configuration key.

Part 2 must apply SPA across the complete valid search space, Deflated Sharpe Ratio using the effective number of trials, Holm multiple-testing correction, seeded block-bootstrap confidence intervals, topology-derived parameter neighbors, fee/slippage/funding stress, temporal/fold consistency, concentration, coverage and long/short checks. Mandatory gates are SPA adjusted p-value <= 0.05, DSR probability >= 0.95, return CI lower bound > 0, at least 60% profitable parameter neighbors, and all eligibility/robustness gates. The final contract is exactly one eligible configuration or `NO_SELECTION`; criteria must never be weakened.

Seeds: sweep/order `20250304`, bootstrap `20250305`, SPA `20250306`. All aggregation orders are lexicographically stable. NaN or infinity in required inputs/outputs marks the affected configuration invalid with a diagnostic.
