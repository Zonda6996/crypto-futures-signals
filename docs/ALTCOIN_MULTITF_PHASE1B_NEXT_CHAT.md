# Prompt для следующего чата — ALT-MULTITF-003 Phase 1B

Продолжи работу в `Zonda6996/crypto-futures-signals` на текущей ветке. Сначала проверь итоговый Phase 1A commit/ancestry и полностью прочитай HANDOFF, roadmap, frozen protocol, Phase 1A report, acquisition/data/audit modules, tests и `.gitignore`.

## Phase 1A evidence — immutable inputs

- Current roster: `527` symbols, frozen before market-data download.
- Official metadata source: `https://www.binance.com/fapi/v1/exchangeInfo`.
- Raw metadata SHA-256: `3c0d748c6ac699a7ed79baa3c7abf9f131b09c3d234ba5e33cc94295bd206242`.
- Raw inventory: `30,321` files / `4,938,089,720` bytes.
- Development: `23,167` files.
- Sealed holdout: `7,154` files / `1,148,688,944` bytes.
- Manifest SHA-256: `5a2cba833af721d60b09177150e0e8866ae3ed3e12c6ca6ceab5aef5d93d73e6`.
- Holdout path: `data/altcoin-multitf-003/sealed-holdout/`.
- Development archive coverage: `[2020-01-01, 2026-01-01)`; requested but unavailable official archive segment `[2019-09-08, 2020-01-01)`.
- `47` current symbols have no development archive; `DOSUSDT` has no holdout archive. Do not mutate roster because of coverage.

## Frozen owner decisions

- Current-roster survivorship/coverage bias is accepted; historical delisted registry is not required.
- Liquidity cohorts: `$10m–25m` and `≥$25m`.
- Minimum age: `30d`.
- Gaps exclude the affected period/decision until clean-window recovery, not the asset forever.
- Parameters may differ only by predefined TF group, never by symbol.
- Hard safety gates are separate from diagnostic scorecard.
- Development requires positive net expectancy, acceptable drawdown and stability in most windows.
- Holdout remains one-time and strict.

## Allowed Phase 1B scope

Only after explicit owner approval:

1. Revalidate roster/manifest/sealed inventory hashes before work.
2. Read and normalize **development only** raw `5m` and funding data.
3. Build `15m/30m/1h/2h/4h/1d` causally from development `5m` only.
4. Audit duplicates, timestamp ordering, gaps, malformed archives/bars, coverage, contract filters and funding alignment.
5. Apply causal age/liquidity/coverage eligibility inside the immutable roster, including the two frozen liquidity cohorts and period-local gap exclusion.
6. Produce normalized manifests, hashes, audit tables/report and focused Phase 1B tests.
7. Update HANDOFF/roadmap/next handoff, commit and push.

## Forbidden

- Do not open, unzip, parse, aggregate, normalize, sample or analyse any sealed-holdout payload.
- Do not download separate higher-timeframe market data.
- Do not run signals, ranking, portfolio construction, PnL, backtest, grid search or parameter selection.
- Do not change the frozen roster, protocol, cohorts, age, gap rule or TF groups because of observed coverage.
- Do not begin Phase 2.

Stop after Phase 1B and report exact normalized coverage, exclusions by reason/period, gaps, hashes, test results, commit and push status.
