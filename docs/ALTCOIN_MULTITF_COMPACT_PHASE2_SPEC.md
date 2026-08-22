# ALT-MULTITF-004 — Phase 2 causal engine specification

Статус: **FROZEN IMPLEMENTATION SPEC**  
Дата: 22 августа 2026 года

## Scope

Phase 2 вычисляет только каузальные признаки, eligibility-filtered cross-sectional ranking inputs, deterministic signals и schema-only portfolio candidates. Подбор параметров, portfolio construction, sizing, execution, PnL, Sharpe/Sortino, drawdown, backtest, walk-forward и holdout запрещены и не реализованы.

## Frozen TF groups and parameters

Параметры одинаковы для всех symbols внутри группы и не могут переопределяться по symbol.

| Group | TF | momentum bars | volatility returns | trend closes | funding publications |
|---|---|---:|---:|---:|---:|
| short | 5m, 15m, 30m | 12 | 24 | 48 | 3 |
| medium | 1h, 2h, 4h | 6 | 12 | 24 | 3 |
| long | 1d | 5 | 10 | 20 | 3 |

## Availability semantics

Decision timestamp `T` использует только bars с `close_time_ms <= T`. Higher-TF bar доступен только после close последнего входящего 5m bar; incomplete bucket отсутствует во входе. Funding record используется только при `publication_time_ms <= T`. Eligibility — causal run, содержащий `T` в полуинтервале `[start_ms, end_exclusive_ms)`; отсутствие run означает `ineligible`. Eligibility применяется **до** feature calculation и ranking.

## Feature definitions

Для положительных closes:

- `return_1 = log(close_t / close_{t-1})`;
- `momentum = log(close_t / close_{t-L})`;
- `volatility = population_std(last V one-bar log returns)`;
- `normalized_momentum = momentum / volatility`, либо `0` при нулевой volatility;
- `trend = sign(close_t - mean(last K closes))`;
- `funding = sum(last F published funding rates)`; при отсутствии записей `0`;
- `ranking_input = normalized_momentum * trend - funding`.

Warm-up требует `max(L, V + 1, K)` закрытых bars. Non-finite и неположительные prices fail closed.

## Schemas and interfaces

Input: immutable `Bar`, `FundingRecord`, `EligibilityRun`, grouped by frozen symbol. Feature output: `FeatureRow`. Ranking output: `SignalRow`, сортировка `ranking_input DESC`, deterministic tie-break `symbol ASC`; rank начинается с 1, percentile равен `(N-rank+1)/N`. Signal direction — sign(score). Portfolio interface возвращает только `PortfolioCandidate`; веса, сделки и доходность отсутствуют.

Diagnostics: counts входных, eligible и featured symbols плюс deterministic sorted exclusions. Missing history, включая `BTWUSDT`, не удаляет symbol из roster и приводит к exclusion/ineligible.

## Safety and limitations

Любой `holdout` path/timeframe отклоняется до чтения. Engine не содержит file loader для holdout. Gap recovery и 30-day clean-window logic принадлежат frozen data-phase eligibility artifact; Phase 2 не пересчитывает eligibility и не ранжирует excluded symbols. Current-liquidity roster несёт survivorship/current-selection bias; реализация не является стратегией и не доказывает edge.
