# ALT-MULTITF-005 — Phase 3 frozen strategy-evaluation specification

Статус: **FROZEN BEFORE FIRST PNL**  
Дата freeze: 23 августа 2026 года

## Граница исследования

Phase 3 использует только development `[2019-09-08, 2026-01-01)`. Любой путь, ключ или timestamp с `holdout`, а также bar `>= 2026-01-01T00:00:00Z`, вызывает fail-closed. Frozen roster, eligibility, normalized data и параметры Phase 2 не меняются. `BTWUSDT` остаётся ineligible. Результат описывает только текущий roster и несёт survivorship/current-selection bias.

## Hypotheses

Проверяются две семьи frozen protocol `ALT-MULTITF-003` без symbol-specific overrides.

- **A:** long-only cross-sectional momentum: TF/lookback/rebalance из раздела 5 исходного protocol, breadth `2/4/8/top20pct`, weights `equal/inverse_vol/capped_rank`, volatility target `10/15/20%`.
- **B:** long-only discrete trades: те же TF/lookback/cycle, entry `next_open/one_bar_confirmation`, stop `1.5/2/3 ATR`, take `none/1.5R/2R/3R`, trailing `none/2ATR/3ATR`, time stop `1/3/7d`, volatility target `10/15/20%`.

Canonical manifest создаётся командой `python -m research.altcoin_multitf_phase3 manifest`. После появления первого PnL manifest менять запрещено; config ID — SHA-256 canonical JSON configuration.

## Execution contract

Решение использует только закрытые bars; fill не раньше следующего open. Base fee `5 bps/side`, base slippage `2 bps/side`, stress slippage `5 bps/side`. Historical funding применяется только в опубликованный timestamp; missing required funding делает replay invalid. Quantity округляется вниз по current snapshot step size; adverse price — по tick. Обязательны minQty/minNotional. Participation `0.5%` trailing causal 24h quote volume, stress `0.25%`. Gross `<=100%`, symbol `<=20%`, cluster `<=40%`, leverage и shorts запрещены. Для B same-bar stop/take разрешается как stop-first. Circuit breaker: rolling 30d return `<=-10%`, exit next open и 7d cash.

## Walk-forward и selection

Outer folds O1–O5 — календарные годы 2021–2025; expanding train начинается 2019-09-08. Purge `97d`, embargo `7d`. Выбор outer configuration выполняется только по предшествующим inner calendar folds; outer test не влияет на собственный выбор. Seed `20260823`.

Frozen family score: `35%` median outer Sharpe, `25%` median Calmar, `15%` positive-fold share, `10%` aggregate stress Sharpe, `10%` concentration score, `5%` inverse turnover percentile, с winsorization 5/95 внутри family.

## Gates

Публикуются все valid, invalid и отрицательные hypotheses. Hard violations: look-ahead, crossed split, missing required funding, impossible fill, negative cash, risk/participation breach или ledger mismatch. Development candidate требует positive net expectancy, max drawdown не хуже `-30%`, большинство positive outer folds и zero hard violations.

Диагностика включает stationary-bootstrap Hansen SPA против cash, 10,000 resamples отдельно по family, и Deflated Sharpe probability с полным числом hypotheses. Winner robustness: stress costs, extra one-bar delay, participation 0.25%, leave-one-year/symbol-out, positive-return adjacent configs `>=60%`, symbol/year concentration и для B top-five-trades. Провал correction/robustness означает `NO WINNER`; это не разрешает replacement.

## Output contract

`reports/artifacts/altcoin-multitf-005-phase3/` содержит frozen manifest/hash, run metadata/input hashes, full leaderboard, per-fold metrics, daily equity/drawdown, fills/ledger для candidates, statistics, robustness и `verdict.json`. Русский отчёт обязан простыми словами показать net return, max drawdown, costs/funding, turnover/activity, стабильность и ограничения. Phase 3 не открывает holdout и не разрешает paper/live trading.
