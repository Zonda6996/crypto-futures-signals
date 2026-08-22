# ALTCOIN Research Engine — план нового исследования

Статус: **PLAN ONLY / IMPLEMENTATION NOT STARTED**

Дата фиксации: 21 августа 2026 года

Следующий protocol ID: `ALT-MULTITF-003` (точные frozen варианты получают суффиксы после Phase 0).

## 1. Цель

Построить воспроизводимый исследовательский контур для Binance USDT perpetual futures и понять, какой торговый продукт устойчивее:

1. **Portfolio family:** периодические сигналы целевых весов `BUY / HOLD / SELL / CASH`.
2. **Trade family:** отдельные сделки с causal entry, stop, take-profit, trailing/time exit.

Семейства исследуются раздельно. Победитель каждого определяется только nested walk-forward. Затем два заранее замороженных победителя сравниваются на одном untouched holdout.

`ALT-LOMOM-002-A` остаётся неизменяемым baseline. Его параметры и результаты не переписываются.

## 2. Рынок и universe

- Источник: Binance USD-M perpetual futures.
- Primary universe: **point-in-time lifecycle universe** — на каждой дате участвуют только реально существовавшие тогда контракты.
- Eligibility использует только прошлые данные: возраст контракта, полноту истории, trailing quote-volume и заранее заданные liquidity rules.
- Delisted и умершие контракты сохраняются в истории.
- Современный fixed basket допустим только как диагностический срез с явной маркировкой survivorship bias, не как primary evidence.

## 3. Матрица таймфреймов

Обязательные TF:

- `5m`
- `15m`
- `30m`
- `1h`
- `2h`
- `4h`
- `1d`

Все горизонты задаются в физическом времени, а не копированием количества баров. Решение использует только полностью закрытые бары; исполнение — не раньше следующего доступного open.

## 4. Контролируемый широкий поиск

До первого расчёта Phase 1 должен сохранить machine-readable search manifest со всеми вариантами. Разрешён только конечный заранее записанный набор:

### Portfolio family

- momentum lookback: `7d`, `14d`, `30d`, `60d`, `90d`;
- rebalance: `1d`, `3d`, `7d`;
- breadth: top `1`, `2`, `4`, `6`, `8` и percentile-аналог для большого universe;
- weights: equal, inverse-volatility, capped rank weight;
- portfolio volatility target: `10%`, `15%`, `20%`;
- long-only primary; long/short — отдельная диагностическая ветка, не смешиваемая с long-only.

### Trade family

Selection/ranking замораживается отдельно от execution. Разрешён конечный набор:

- entry: next-open или causal pullback/confirmation;
- stop: ATR/realized-volatility multiple;
- take: fixed R ladder или отсутствие fixed take;
- exit: trailing, rank exit, time exit;
- portfolio circuit breaker и правила повторного входа.

Точные множители и диапазоны обязаны быть записаны до запуска. После просмотра результата расширять диапазон нельзя.

## 5. Data split

### Research zone

Данные строго раньше `2026-01-01T00:00:00Z` используются для nested walk-forward:

- outer folds оценивают переносимость;
- inner folds выбирают вариант только внутри прошлого;
- purge/embargo не допускает пересечения lookback и holding horizon;
- ни один outer-test fold не участвует в выборе параметров.

### Sealed holdout

Весь доступный диапазон `[2026-01-01T00:00:00Z, holdout_snapshot_end)` запечатывается до исследования:

- отдельный manifest: файлы, timestamps, SHA-256;
- search, ranking и debugging не имеют права читать эти строки;
- holdout открывается **ровно один раз** после freeze одного победителя каждого семейства;
- короткий holdout даёт только предварительное независимое свидетельство, не окончательное доказательство.

## 6. Реалистичный replay

Engine обязан моделировать:

- комиссии, slippage и funding;
- min quantity, tick/step size и contract lifecycle;
- participation cap по causal quote-volume;
- недоисполнение, cash residual и turnover;
- gap-through-stop без идеального fill по stop price;
- одновременные stop/take внутри бара консервативно либо на lower-TF данных;
- funding только за реально пересечённые timestamps;
- полные ledgers решений, заявок, fills, позиций, equity и attribution.

## 7. Ранжирование и защита от data mining

Профиль риска — умеренный:

- приоритет median outer-fold Sharpe/Calmar и стабильности;
- target volatility ориентировочно `15–20%`;
- max drawdown желательно не хуже `−25%`;
- обязательны stress costs, concentration, turnover и liquidity diagnostics;
- кандидат должен быть положительным в большинстве outer folds и не зависеть от одного актива, года или нескольких сделок;
- применяются Deflated Sharpe / Probability of Backtest Overfitting либо эквивалентная multiple-testing correction;
- leaderboard показывает все варианты, а не только победителя.

Portfolio и Trade family имеют отдельные leaderboard и PASS/FAIL. До holdout выбирается ровно один победитель каждого семейства.

## 8. Фазы

0. **Protocol freeze:** точный manifest данных, universe rules, search space, folds, costs, score и PASS/FAIL. Только документация.
1. **Data/lifecycle audit:** получить и нормализовать данные, создать hashes; sealed holdout не анализировать.
2. **Causal engine:** replay, guards, unit/integration/property tests; без выбора победителя.
3. **Nested walk-forward sweep:** два раздельных leaderboard, без доступа к holdout.
4. **Robustness:** costs, delay, liquidity, concentration, regimes и perturbation tests без расширения grid.
5. **Freeze shortlist:** один portfolio winner и один trade winner, immutable config/hash.
6. **One-time holdout:** один запуск двух frozen winners, механический PASS/FAIL.
7. **Paper signals:** только прошедшие варианты; реальные ордера и live capital не входят в этот план.

## 9. Практический результат

Engine должен выдавать понятный торговый output.

Portfolio family:

```text
Timestamp, symbol, current_weight, target_weight, action, reason, next_rebalance
```

Trade family:

```text
Timestamp, symbol, side, entry, stop, take_plan, size, invalidation, max_holding
```

До Phase 6 это исследовательские результаты, а не разрешение торговать.

## 10. Текущая точка остановки

План утверждён владельцем, но **код, скачивание данных и расчёты не начинались**. Следующий чат выполняет только Phase 0: уточняет и фиксирует все ещё незаданные числа, manifests и gates. Если формулировка допускает выбор трактовки, он обязан спросить владельца до кода и расчётов.
