# ALT-MULTITF-003 — frozen protocol

Статус: **FROZEN WITH OWNER AMENDMENTS A1+A2 / PHASE 1A RE-APPROVED**

Дата freeze: 22 августа 2026 года

Дата owner amendment A1: 22 августа 2026 года

Дата owner amendment A2: 22 августа 2026 года

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

## 3. Owner amendment A1 — current-roster universe

Владелец явно отменил требование полного исторического lifecycle registry и принял survivorship/coverage bias. Primary universe фиксируется один раз в Phase 1A как текущий на момент acquisition список Binance USD-M linear USDT-margined perpetual contracts. Snapshot roster, полный raw API response или официальный эквивалент, source URL, acquisition timestamp и SHA-256 обязательны; roster после начала расчётов менять нельзя.

На каждом historical decision timestamp контракт из frozen current roster eligible только если одновременно:

1. это Binance USD-M linear USDT-margined perpetual (`contractType=PERPETUAL`, quote/settle asset `USDT`), не delivery, не coin-margined и не synthetic index;
2. для timestamp существуют реальные raw `5m` bars; входы до первого доступного observation запрещены;
3. возраст от первого доступного tradable `5m` observation не менее `30d`;
4. базовые bars, требуемые конкретным causal lookback/ATR/volatility calculation, непрерывны и валидны; отдельный gap исключает только затронутый период, а не symbol целиком;
5. median causal daily quote volume за последние 30 полных UTC-дней не менее `$10m`; cohort `secondary` = `$10m–25m`, cohort `primary` = `>= $25m`, результаты и capacity публикуются раздельно;
6. доступны causal price, current snapshot contract filters и funding, необходимые для решения/удержания.

Delisted/expired/failed contracts, отсутствующие в frozen current roster, намеренно не входят в исследование. Исторические point-in-time изменения tick/step/minNotional могут быть недоступны; использование current snapshot filters должно маркироваться как отдельное ограничение. Symbol rename/migration не склеивается без однозначной официальной идентичности. Результаты отвечают только на вопрос о поведении текущих доступных контрактов на их доступной истории и не являются survivorship-unbiased оценкой всех когда-либо существовавших Binance contracts.

Bars, volume и funding не импутируются. При missing/duplicate/out-of-order bar запрещены решения и fills, чьи required input/holding interval пересекает дефект; symbol автоматически возвращается после восстановления непрерывного causal окна, требуемого конкретной метрикой. Единичный исторический gap не исключает symbol за другие чистые периоды. Duplicate разрешено только детерминированно удалить при byte-identical payload; конфликтующие duplicates блокируют затронутый период. Неполный последний bar не используется. Отсутствующий funding timestamp при открытой позиции делает конкретный replay/config invalid (не нулевой funding). Universe membership, liquidity cohort и причины временного исключения логируются на каждом decision.

## 4. Общие causal правила

Обязательные TF: `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `1d`. Старшие bars агрегируются из закрытых `5m` bars по UTC; решение принимается после закрытия bar, fill — не ранее следующего доступного open. Lookback задаётся физическим временем и требует полного окна. Momentum — total price return `close(t-1 closed)/close(t-lookback)-1`; funding не входит в rank, но входит в PnL.

Каждая `(family, TF, lookback, execution/risk choices)` — отдельная hypothesis. Параметры разрешено выбирать раздельно по TF или заранее заданным TF-группам (`5m/15m/30m`, `1h/2h`, `4h/1d`), но никогда по отдельному symbol. Все допустимые конфигурации до первого backtest сериализуются в immutable machine-readable manifest с canonical config ID и SHA-256. Cartesian product используется только в пределах явно перечисленных значений; неописанные фильтры, indicators, assets и значения запрещены.

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

Multiple-testing diagnostics применяются отдельно к полному manifest каждого family: stationary-bootstrap Hansen SPA против cash/null, family-wise `alpha=5%`, block length выбран один раз как `max(7d, 2 × median holding/rebalance interval)` и записан до sweep; не менее 10,000 deterministic-seed resamples. Дополнительно Deflated Sharpe Ratio учитывает число всех hypotheses family, skew/kurtosis и длину sample. SPA `p>0.05` или DSR probability `<95%` являются обязательными предупреждениями scorecard, но сами по себе не уничтожают кандидата; скрывать их запрещено.

## 10. Robustness и concentration gates

До freeze winner, без расширения grid, каждый кандидат получает полный robustness scorecard:

1. base и stress costs;
2. one-bar execution delay (дополнительно к entry rule);
3. participation cap stress `0.25%`;
4. leave-one-year-out;
5. leave-one-symbol-out;
6. доля прибыльных one-coordinate parameter neighbours из frozen grid;
7. Family A: доли top symbol и top calendar year в положительном PnL;
8. Family B: те же доли и top 5 trades;
9. turnover, capacity, funding attribution и equity/fill ledger reconciliation.

Hard FAIL дают только causal/accounting/limit violations, отрицательный aggregate stress return, full outer OOS drawdown хуже `−30%` или отсутствие большинства положительных доступных outer folds. Leave-one-out, neighbour stability, concentration, SPA/DSR и малое число сделок — обязательные warnings с точными значениями, а не автоматическая смерть прибыльной конфигурации. При total PnL `<=0` кандидат всё равно hard FAIL.

## 11. Mechanical PASS/FAIL

Конфигурация получает статус **DEVELOPMENT-QUALIFIED** только если одновременно:

- aggregate base и stress compounded return `>0`;
- большинство доступных outer folds имеет положительный net return; unavailable fold документируется и не считается отрицательным;
- full outer OOS max drawdown не хуже `−30%`;
- equity/fill/funding ledger полностью reconciled;
- zero hard violations причинности, impossible fills, cash/exposure/capacity limits и data-boundary rules.

Median Sharpe `0.75`, median Calmar `0.50`, positive-fold share `60%`, SPA `5%`, DSR `95%`, concentration limits, neighbour stability и minimum trade count сохраняются в scorecard как заранее объявленные ориентиры/warnings. Они не являются отдельными veto, если hard gates выше пройдены. Все family и hypotheses публикуются независимо; отсутствие qualified config означает FAIL соответствующего family, но не запрещает выбрать qualified config другого family до открытия holdout.

## 12. Freeze shortlist и одноразовый holdout

После Phase 4 среди всех DEVELOPMENT-QUALIFIED configs обоих family замораживается ровно один highest-score final candidate. Tie в пределах `1%` абсолютного score разрешается последовательно: меньший turnover, затем меньшая absolute max drawdown, затем lexicographically smallest canonical config ID. Freeze artifact содержит config, code/data/manifest hashes, scorecard, warnings, ledgers и owner approval; после него код и параметры immutable.

Holdout может быть открыт только для этого одного frozen candidate после отдельного owner approval. В Phase 6 выполняется ровно один invocation на `[2026-01-01, 2026-08-01)`. Повторный запуск, debugging по holdout, замена кандидата, выбор TF/asset/parameter и retuning запрещены даже при crash после чтения payload; технический сбой документируется как inconclusive, право открытия считается израсходованным.

Holdout PASS требует: net return `>0` base и stress, max drawdown не хуже `−30%`, полностью reconciled ledger и zero hard violations. Sharpe, monthly/symbol/trade concentration и остальные scorecard metrics публикуются как диагностика и не меняют заранее замороженный выбор.

## 13. Governance и следующие фазы

Phase 0 завершает только документацию. После отдельного owner approval разрешена **только Phase 1: data/lifecycle audit, physical sealing, manifests и hashes без signal/PnL/backtest и без чтения holdout payload исследовательским процессом**. Engine implementation относится к отдельной последующей Phase 2 и сейчас запрещена.

Для операционной безопасности Phase 1 разделена без изменения research rules:

- **Phase 1A — acquisition/sealing:** получить и заморозить current-roster snapshot по amendment A1, затем выполнить raw acquisition, физическое разделение development/holdout и immutable file inventory с SHA-256. Полный historical lifecycle gate больше не требуется; roster должен быть зафиксирован до market-data acquisition и не изменяться по результатам coverage.
- **Phase 1B — normalization/eligibility:** только после PASS Phase 1A и отдельного owner approval разрешены чтение development payload, quality audit, causal eligibility внутри frozen current roster и агрегация старших TF. Holdout payload остаётся недоступным.

STOP любой части запрещает переход к следующей. Это разделение не разрешает новые источники, параметры, signals, PnL или backtest и не изменяет frozen calendar/search space.

Любая неоднозначность при реализации решается консервативным STOP и owner amendment до расчёта, а не выбором после просмотра результата.
