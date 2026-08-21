# ALT-MULTITF-003 — frozen protocol

Статус: **FROZEN / PHASE 0 COMPLETE / IMPLEMENTATION NOT APPROVED**

Дата freeze: 22 августа 2026 года

Рынок: Binance USD-M linear USDT perpetual futures

Семейства: `A` portfolio momentum и `B` discrete momentum trades

## 1. Назначение и независимость

Этот документ до загрузки данных и расчётов фиксирует новое исследование `ALT-MULTITF-003`. Оно не является продолжением или retuning `ALT-LOMOM-002-A`. Последний остаётся неизменяемым contaminated TRAIN baseline: Sharpe `1,1508`, return `+270,37%`, stress return `+254,18%`, max drawdown `−28,00%`; его fixed-basket survivorship/selection bias не переносится в evidence нового исследования.

Изменение любого правила ниже после первого просмотра результатов создаёт новый protocol ID и требует нового будущего holdout. Phase 0 не разрешает код, данные, backtest, paper/live trading или открытие holdout.

## 2. Календарь и sealed holdout

Все границы — UTC, интервалы полуоткрытые `[start, end)`.

- Research-development: `[2019-09-08T00:00:00Z, 2026-01-01T00:00:00Z)`.
- Sealed holdout snapshot: `[2026-01-01T00:00:00Z, 2026-08-01T00:00:00Z)` — все полные месяцы 2026 года, доступные на дату freeze.
- Данные `>= 2026-08-01T00:00:00Z` не являются частью этого frozen holdout и не могут быть присоединены к нему после freeze.
- Phase 1 должна физически разделить development и holdout, записать file list, row ranges, timestamps, sizes и SHA-256. Исследовательские процессы до Phase 6 не получают путь/доступ к holdout payload; разрешены только metadata и hashes.

### 2.1 Outer folds

| Fold | Outer train | Purged boundary | Outer test |
|---|---|---|---|
| O1 | `[2019-09-08, 2021-01-01)` | последние 97d train не создают позиции, пересекающие test | `[2021-01-01, 2022-01-01)` |
| O2 | `[2019-09-08, 2022-01-01)` | то же | `[2022-01-01, 2023-01-01)` |
| O3 | `[2019-09-08, 2023-01-01)` | то же | `[2023-01-01, 2024-01-01)` |
| O4 | `[2019-09-08, 2024-01-01)` | то же | `[2024-01-01, 2025-01-01)` |
| O5 | `[2019-09-08, 2025-01-01)` | то же | `[2025-01-01, 2026-01-01)` |

Для каждого outer fold выбор конфигурации выполняется только inner folds. Inner validation — каждый полный календарный год от 2020 до года перед outer test; inner train расширяется от `2019-09-08` до начала соответствующего validation-года. Если после purge нет достаточной истории/событий, inner fold отмечается unavailable, а не меняется.

Purge равен `97d` (`90d` maximum lookback + `7d` maximum holding); embargo после каждого validation/test равен `7d`. Сигнал до границы не может открыть или удерживать позицию после неё. Outer test никогда не участвует в выборе своего кандидата.

## 3. Point-in-time lifecycle universe

На каждом decision timestamp контракт eligible только если одновременно:

1. это Binance USD-M linear USDT-margined perpetual (`contractType=PERPETUAL`, quote/settle asset `USDT`), не delivery, не coin-margined и не synthetic index;
2. timestamp находится между authoritative onboard/open и delist/close timestamps Binance;
3. возраст после первого tradable timestamp не менее `90d`;
4. присутствует не менее `99%` ожидаемых закрытых базовых `5m` bars за trailing `30d`, без gap длиннее `30m`;
5. median causal daily quote volume за последние 30 полных UTC-дней не менее `$25m`;
6. доступны causal price, contract filters и funding, необходимые для решения/удержания.

Lifecycle registry строится по историческим Binance metadata/archives и сохраняет delisted/failed contracts. Текущий roster не может заменять registry. Symbol rename/migration считается новым lifecycle, если Binance не даёт однозначную непрерывную идентичность; склейка запрещена. После delist новые входы запрещены, открытая позиция закрывается по последнему реально исполнимому observation с costs и отдельным `forced_delist` reason.

Bars, volume, funding и lifecycle timestamps не импутируются. При missing/duplicate/out-of-order bar актив исключается с первого затронутого decision до первого следующего decision после полного clean trailing window. Duplicate разрешено только детерминированно удалить при byte-identical payload; конфликтующие duplicates блокируют актив. Неполный последний bar не используется. Отсутствующий funding timestamp при открытой позиции делает конкретный replay/config invalid (не нулевой funding). Universe membership и причины исключения логируются на каждом decision.

## 4. Общие causal правила

Обязательные TF: `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `1d`. Старшие bars агрегируются из закрытых `5m` bars по UTC; решение принимается после закрытия bar, fill — не ранее следующего доступного open. Lookback задаётся физическим временем и требует полного окна. Momentum — total price return `close(t-1 closed)/close(t-lookback)-1`; funding не входит в rank, но входит в PnL.

Каждая `(family, TF, lookback, execution/risk choices)` — отдельная hypothesis. Все допустимые конфигурации до первого backtest сериализуются в immutable machine-readable manifest с canonical config ID и SHA-256. Cartesian product используется только в пределах явно перечисленных значений; неописанные фильтры, indicators, assets и значения запрещены.

## 5. Семейство A — portfolio momentum

Primary family long-only. На каждом rebalance eligible contracts ранжируются по momentum по убыванию; отрицательный/non-finite momentum не покупается, незанятый вес остаётся cash.

| TF | Lookbacks | Rebalance intervals |
|---|---|---|
| 5m | `7d, 14d, 30d, 60d, 90d` | `6h, 1d` |
| 15m | те же | `12h, 1d` |
| 30m | те же | `1d, 3d` |
| 1h | те же | `1d, 3d, 7d` |
| 2h | те же | `1d, 3d, 7d` |
| 4h | те же | `1d, 3d, 7d` |
| 1d | те же | `3d, 7d` |

Допустимые breadth: `top 2`, `top 4`, `top 8`, `top 20%` (`ceil(0.20*N)`, минимум 2, максимум N). Если eligible positive-momentum names меньше требуемого breadth, используются доступные, остаток — cash.

Weights: equal; inverse-vol (inverse trailing `30d` realized volatility); capped-rank (линейные rank scores `N..1`, нормированные, затем iterative cap `20%` на symbol). Volatility targets: `10%`, `15%`, `20%` annualized. Portfolio scaling использует только trailing 30 полных дней close-to-close portfolio returns, EWMA half-life `10d`, annualization `365d`; multiplier `min(1, target/forecast)`, без leverage.

## 6. Семейство B — discrete momentum trades

Long-only entries используют тот же momentum rank, lookbacks и ranking/re-entry intervals из таблицы соответствующего TF. На cycle выбирается `top 20%` (`ceil`, минимум 2); одновременно действуют risk limits раздела 8.

Entry:

- `next_open`: market fill на следующем доступном bar open;
- `one_bar_confirmation`: после ranking bar дождаться ровно одного полного bar того же TF; вход на следующем open только если confirmation close выше ranking close и контракт всё ещё eligible, иначе сигнал истекает.

Exit grid:

- initial stop: `1.5`, `2.0`, `3.0 ATR`;
- take-profit: `none`, `1.5R`, `2R`, `3R`;
- trailing: `none`, `2ATR`, `3ATR`, активируется только после first touch `+1R`, никогда не ослабляется;
- time-stop: `1d`, `3d`, `7d` в физическом времени.

ATR — Wilder true range, trailing `14` bars того же TF, полностью закрытые bars. Initial `R` — distance entry-to-initial-stop. Fixed take остаётся от initial R. При stop/take в одном bar без lower-TF доказательства первым считается stop. Gap through stop/take исполняется по следующей доступной цене, не по идеальному level. Exit по earliest из stop, take, trailing, time, loss of eligibility или delist. Повторный вход в symbol разрешён только на следующем ranking cycle после полного выхода.

Circuit breaker: если causal rolling `30d` portfolio return `<= −10%`, новые entries запрещены и exposure закрывается на следующем доступном open; затем ровно `7d` cash, без досрочного reset.

## 7. Execution, fees, funding и capacity

- Base fee: `5 bps` на каждую сторону каждого fill.
- Base slippage: `2 bps/side`; stress slippage: `5 bps/side`. Adverse direction применяется также к forced exits и gaps.
- Stress не меняет fee (`5 bps/side`).
- Funding списывается/начисляется по фактической исторической rate и только если позиция пересекает точный Binance funding timestamp; notional определяется mark price на timestamp. Missing rate не заменяется нулём.
- Quantity округляется вниз по point-in-time step size, price — adverse по tick size; minQty/minNotional обязательны. Неисполняемый residual остаётся cash.
- Максимальный fill на symbol за decision — `0.5%` causal trailing `24h` quote volume. Все одновременно созданные orders агрегируются до применения cap; недоисполненная часть отменяется, не переносится.
- Market impact сверх указанного slippage не моделируется; поэтому нарушение participation cap — hard invalidation, а не оптимистичный fill.

## 8. Risk и limits

Gross exposure `<=100%` equity; leverage и net short запрещены. Symbol exposure `<=20%`. Correlated cluster exposure `<=40%`: clusters на каждом decision — connected components eligible symbols с pairwise Pearson correlation `>=0.75` по общим trailing `90d` daily returns (минимум 60 совместных дней); symbols без 60 дней образуют singleton. Все лимиты применяются после volatility scaling и до округления; округление не может увеличить limit.

Для trades initial risk budget распределяется поровну между выбранными entries, а quantity ограничивается одновременно stop-distance sizing, vol-target multiplier, gross/symbol/cluster/participation limits. Варианты vol target те же `10/15/20%`; forecast как в family A. Cash разрешён всегда.

Любое look-ahead, crossed split, limit breach, negative cash, impossible fill, missing required funding или ledger reconciliation error — hard violation и FAIL конфигурации.

## 9. Selection score и multiple testing

Метрики считаются только по outer-test observations. Внутри каждого family все hypotheses публикуются, включая invalid/negative. Для каждой metric значения winsorize на 5/95 percentile внутри family и переводятся в percentile rank `[0,1]`; где меньше лучше, rank инвертируется.

Score:

- `35%` median outer-fold Sharpe;
- `25%` median outer-fold Calmar;
- `15%` positive outer-fold share;
- `10%` aggregate stress Sharpe;
- `10%` concentration score (`1 − max(top-symbol share, top-year share, а для B также top-5-trades share)`; shares clipped `[0,1]`);
- `5%` turnover score (inverse rank).

Sharpe annualizes daily net returns by `sqrt(365)`; Calmar = annualized compounded return / absolute max drawdown, undefined при истории менее года или zero drawdown and ranked conservatively. Zero-activity folds не считаются positive и получают Sharpe/Calmar 0.

Multiple-testing correction применяется отдельно к полному manifest каждого family: stationary-bootstrap Hansen SPA против cash/null, family-wise `alpha=5%`, block length выбран один раз как `max(7d, 2 × median holding/rebalance interval)` и записан до sweep; не менее 10,000 deterministic-seed resamples. Дополнительно Deflated Sharpe Ratio учитывает число всех hypotheses family, skew/kurtosis и длину sample; требуется probability `>=95%`. Провал любого correction gate означает отсутствие winner family.

## 10. Robustness и concentration gates

До freeze winner, без расширения grid, каждый кандидат обязан пройти:

1. base и stress costs;
2. one-bar execution delay (дополнительно к entry rule);
3. participation cap stress `0.25%`;
4. leave-one-year-out: aggregate net return положителен после исключения любого одного outer-test года;
5. leave-one-symbol-out: aggregate net return положителен после исключения любого одного symbol с положительным attribution;
6. parameter neighbours, существующие в frozen grid: не менее 60% one-coordinate adjacent configs имеют положительный aggregate base return;
7. Family A: top symbol `<=30%` положительного PnL и ни один календарный год `>50%` положительного PnL;
8. Family B: те же limits и top 5 trades `<=40%` положительного PnL;
9. turnover, capacity, funding attribution и equity/fill ledger полностью reconciled.

При total PnL `<=0` concentration gate автоматически FAIL; отрицательные contributors не вычитаются из denominator положительного PnL.

## 11. Mechanical PASS/FAIL

Family получает PASS только если существует конфигурация, которая одновременно:

- имеет все 5 outer folds (минимум 4 допускается только если один fold объективно unavailable из-за отсутствия eligible lifecycle universe, не из-за слабого результата);
- positive outer-fold share `>=60%`;
- median outer Sharpe `>=0.75`;
- median outer Calmar `>=0.50`;
- aggregate stress compounded return `>0`;
- full outer OOS max drawdown не хуже `−30%`;
- проходит SPA `5%`, DSR probability `>=95%`, все robustness/concentration gates;
- имеет zero hard violations.

Иначе family FAIL и победитель не назначается. PASS одного family не компенсирует FAIL другого и не разрешает подбирать replacement после holdout.

## 12. Freeze shortlist и одноразовый holdout

После Phase 4 среди PASS configs каждого family замораживается ровно один highest-score winner. Tie в пределах `1%` абсолютного score разрешается последовательно: меньший turnover, затем меньшая absolute max drawdown, затем lexicographically smallest canonical config ID. Freeze artifact содержит config, code/data/manifest hashes, score inputs, ledgers и owner approval; после него код и параметры immutable.

Holdout может быть открыт только если оба family имеют по одному frozen winner. Если хотя бы одно family FAIL, Phase 6 не проводится без нового owner protocol; нельзя заменить отсутствующего winner. В Phase 6 выполняется ровно один invocation, который одновременно оценивает два frozen winners на `[2026-01-01, 2026-08-01)`. Повторный запуск, debugging по holdout, выбор TF/asset/parameter и retuning запрещены даже при crash после чтения payload; технический сбой документируется как inconclusive, право открытия считается израсходованным.

Holdout PASS каждого winner требует: net return `>0` base и stress, Sharpe `>0`, max drawdown не хуже `−30%`, zero hard violations и соблюдение symbol/year/trade concentration limits (year gate для семимесячного holdout заменяется monthly gate: ни один месяц `>50%` positive PnL). Результаты обоих публикуются независимо; holdout не меняет pre-holdout ranking.

## 13. Governance и следующие фазы

Phase 0 завершает только документацию. После отдельного owner approval разрешена **только Phase 1: data/lifecycle audit, physical sealing, manifests и hashes без signal/PnL/backtest и без чтения holdout payload исследовательским процессом**. Engine implementation относится к отдельной последующей Phase 2 и сейчас запрещена.

Для операционной безопасности Phase 1 разделена без изменения research rules:

- **Phase 1A — acquisition/sealing:** сначала PASS полного point-in-time lifecycle registry, затем raw acquisition, физическое разделение development/holdout и immutable file inventory с SHA-256. Symbol-addressed market data нельзя массово загружать до PASS registry gate.
- **Phase 1B — normalization/eligibility:** только после PASS Phase 1A и отдельного owner approval разрешены чтение development payload, quality audit, canonical lifecycle registry, causal eligibility и агрегация старших TF. Holdout payload остаётся недоступным.

STOP любой части запрещает переход к следующей. Это разделение не разрешает новые источники, параметры, signals, PnL или backtest и не изменяет frozen calendar/search space.

Любая неоднозначность при реализации решается консервативным STOP и owner amendment до расчёта, а не выбором после просмотра результата.
