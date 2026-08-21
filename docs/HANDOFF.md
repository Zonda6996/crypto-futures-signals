# Project handoff

Обновлено: 21 августа 2026 года.

## Где продолжать

- Репозиторий: `Zonda6996/crypto-futures-signals`
- Рабочая ветка: `v0/crypto-futures-analysis-88d9d19a`
- Roadmap: [`docs/roadmap.md`](./roadmap.md)
- Phase 1: [`reports/PHASE1_AUDIT.md`](../reports/PHASE1_AUDIT.md)
- Оригинальная Phase 2: [`reports/PHASE2_WALK_FORWARD.md`](../reports/PHASE2_WALK_FORWARD.md)
- Дополнительный повтор Phase 2: [`reports/PHASE2_WALK_FORWARD_REPEAT.md`](../reports/PHASE2_WALK_FORWARD_REPEAT.md)
- Оригинальная Phase 3: [`reports/PHASE3_PARAMETER_STABILITY.md`](../reports/PHASE3_PARAMETER_STABILITY.md)
- Дополнительная повторная robustness-проверка: [`reports/PHASE3_ROBUSTNESS.md`](../reports/PHASE3_ROBUSTNESS.md)
- Phase 4: [`reports/PHASE4_ECONOMIC_MECHANISM.md`](../reports/PHASE4_ECONOMIC_MECHANISM.md)
- Дополнительная M15/M30 robustness-проверка: [`reports/TIMEFRAME_ROBUSTNESS_M15_M30.md`](../reports/TIMEFRAME_ROBUSTNESS_M15_M30.md)
- Отдельная regime/concentration-диагностика: [`reports/REGIME_CONCENTRATION.md`](../reports/REGIME_CONCENTRATION.md)
- Phase 5 protocol: [`docs/PHASE5_PROTOCOL.md`](./PHASE5_PROTOCOL.md)
- Phase 5 falsification: [`reports/PHASE5_FALSIFICATION.md`](../reports/PHASE5_FALSIFICATION.md)

Новый чат сначала читает этот файл, четыре фазовых отчёта и roadmap.

## Цель

Искать воспроизводимый edge для crypto perpetual futures небольшими фазами. Не выдавать положительный исторический результат за подтверждённую стратегию; учитывать исполнение BingX, funding, multiple testing и закрытый holdout.

## Текущий кандидат

Статус: **положительный walk-forward и широкий положительный robustness-кластер, но strict Phase 3 pass не пройден; TEST закрыт**.

- ETHUSDT perpetual, long, 1h;
- `vwap_distance_24` в верхнем квартиле прошлого calibration-окна;
- BTC в медвежьем 24h-режиме;
- высокая волатильность относительно медианы прошлого calibration-окна;
- stop `1,5 ATR`, take `2 ATR`, максимум `24h`;
- вход на open следующей свечи.

## Статус фаз

- Phase 1 завершена: аудит исполнения, причинности, данных и TRAIN-only calibration.
- Оригинальная Phase 2 завершена: четыре anchored/rolling walk-forward-схемы только внутри TRAIN+VALIDATION; дополнительный повтор хранится отдельно.
- Оригинальная Phase 3 завершена: декартова карта из 256 VALIDATION-конфигураций; дополнительная повторная robustness-проверка costs/windows/concentration/one-factor neighbors хранится отдельно.
- Phase 4 завершена: простой специфический 24h continuation-механизм не подтверждён.
- Phase 5 завершена: frozen 1h прошёл все 7 заранее зафиксированных pre-TEST falsification-критериев; отдельный one-bar-delay stress отрицателен.
- Закрытый TEST ни в одной фазе не оценивался.

## Результаты Phase 2

Оригинальная Phase 2: все четыре заданные walk-forward-схемы дали положительный объединённый OOS. Следующие числа относятся только к дополнительному повтору Phase 2 при 0,10% round trip:

- anchored: 42 сделки, expectancy `+0,221R`, total `+9,279R`, PF `1,602`, 3/4 положительных окон;
- rolling: 75 сделок, expectancy `+0,086R`, total `+6,476R`, PF `1,195`, 2/4 положительных окон.

Объединённый OOS положителен, но rolling без лучших пяти сделок даёт `−0,044R`.

## Результаты Phase 3

Оригинальная Phase 3: на одной VALIDATION-выборке положительны 231/256 точек при 0,10%, а локальный кластер — 9/9; это диагностика поверхности, не новый поиск кандидата.

Следующие результаты относятся только к дополнительной повторной robustness-проверке на TRAIN+VALIDATION `[0, 35059)`:

- при costs 0,05–0,16% untrimmed anchored и rolling остаются положительными;
- при 0,16%: anchored `+8,170R`, rolling `+4,053R`;
- все три заданных window policies дают положительный untrimmed итог в обеих схемах;
- 11/11 соседей положительны anchored, 10/11 rolling;
- медианный сосед: anchored `+7,484R`, rolling `+6,304R`;
- rolling без top-5 отрицателен при 0,10%, 0,12% и 0,16%; при 0,16% `−2,385R`;
- единственный отрицательный rolling-сосед — take `3,0 ATR`, `−1,497R`.

Предварительно заданный strict rule требовал положительный frozen результат после удаления top-5 в обеих схемах. Требование не выполнено, поэтому `strict pass = false`. Не выбирать новый лучший вариант из карты соседей.

## Дополнительная M15/M30 robustness-проверка

При механическом сохранении часовых горизонтов M30 и M15 положительны на VALIDATION при 0,10%: соответственно `+2,675R` и `+4,233R`. Но без top-5 результаты равны `−3,791R` и `−2,173R`; при 0,16% M15 также становится отрицательным (`−0,238R`). Заранее заданный строгий критерий поддержки не пройден; параметры не переотбирались, TEST закрыт.

## Отдельная regime/concentration-диагностика

Диагностика выполнена отдельно от Phase 2–4 на полном pre-TEST TRAIN+VALIDATION-срезе 2021–2024 при frozen-параметрах и расходах 0,10%. Это описательный анализ концентрации, не новая OOS-оценка. BTC-режимы размечены каузально: trailing 90-day return и trailing 30-day realized volatility; пороги — expanding median только предшествующих валидных наблюдений.

- 1h: 185 сделок, `+16,387R`; top-5 = 40,1% total, без top-5 `+9,808R`.
- M30: 264 сделки, `+7,926R`; top-5 = 83,0%, без top-5 `+1,348R`.
- M15: 401 сделка, `+0,654R`; top-5 = 1003,3%, без top-5 `−5,910R`.
- Leave-one-year-out и leave-one-regime-out сохранены в отдельных JSON; сделки — в отдельных CSV.
- Ранние сделки без достаточной 90-day/past-threshold истории выделены как `insufficient_history`, а не классифицированы задним числом.
- TEST с `2025-01-01` не загружался, не анализировался и не открывался.

Вывод: 1h сохраняет положительный запас после top-5 на полном pre-TEST срезе, M30 имеет слабый положительный остаток, M15 полностью зависит от экстремальных сделок. Это не отменяет отрицательные trimmed-результаты исходных дополнительных rolling/timeframe экспериментов: эксперименты и их выборки нельзя смешивать.

## Phase 5 — финальная pre-TEST falsification

Protocol был зафиксирован до расчётов. Frozen 1h-кандидат получил **PASS 7/7** на описательном полном TRAIN+VALIDATION-срезе 2021–2024:

- baseline: 185 сделок, `+16,387R`; без top-5 `+9,808R`;
- без лучшего года (2024): `+7,294R`;
- без лучшего непрерывного 90-day кластера: `+8,330R`;
- costs 0,16%: `+12,210R`;
- положительны 78,4% rolling 12-month окон;
- каждый обязательный leave-one-causal-regime-out положителен;
- combined execution stress: `+4,792R`.

Важная отрицательная диагностика, которая не входила в семь verdict-критериев: дополнительная задержка входа на один 1h-бар дала `−2,358R`. Максимальный период без нового equity high — около 970 дней. Поэтому PASS разрешает только подготовить immutable TEST-opening memo, но не означает подтверждённый edge и не разрешает открывать TEST.

## Связь с Phase 4

Phase 4 не обнаружила специфический положительный 24h drift: средний gross return полного сигнала через 24 часа `−0,018%`, преимущество над главным контролем `−0,547` п.п. Возможный эффект Phase 2/3 может быть path-dependent и связан с stop/take, а не с простым continuation.

## Cost model BingX

- 2,5 bps на сторону = 0,05% round trip;
- 5 bps на сторону = 0,10% round trip;
- 0,12% включает реалистичную надбавку slippage;
- 0,16% — stress.

## Как воспроизвести

```bash
python3 -m unittest discover -s tests -v
python3 -m research.phase2_walk_forward
python3 -m research.phase2_walk_forward_repeat
python3 -m research.phase3_parameter_map
python3 -m research.phase3_robustness
python3 -m research.phase4_mechanism
python3 -m research.timeframe_robustness
python3 -m research.regime_concentration
python3 -m research.phase5_falsification
```

Market cache скачивается в `data/cache/` и исключён из Git.

## Ограничения

- кандидат появился после широкого перебора; selection bias остаётся;
- strict Phase 3 pass не пройден из-за top-5 concentration rolling;
- результат по периодам неравномерен и концентрирован в 2024;
- economic mechanism не подтверждён на 24h;
- карта соседей однофакторная и не является новым поиском optimum;
- фактические BingX fills отсутствуют;
- полный pre-TEST concentration-срез не является новой OOS-оценкой; M15 без top-5 отрицателен, а ранний `insufficient_history`-режим нельзя интерпретировать как торговый фильтр;
- TEST запрещено открывать без отдельного явного решения.

## Ровно один следующий шаг

**Подготовить отдельный immutable TEST-opening memo без загрузки или просмотра TEST.**

Memo должен зафиксировать commit и hashes артефактов, единственный frozen запуск, критерий успеха и запрет повторной настройки. После memo всё ещё требуется новое явное разрешение владельца; без него TEST не трогать и кандидата не продвигать в paper trading.

## Правила для следующих чатов

- не пушить в `main`;
- делать одну фазу за раз;
- не называть положительный walk-forward подтверждённым edge;
- не выбирать новый candidate из Phase 3 neighbor map;
- не открывать TEST до отдельного явного решения;
- в конце к��ждой фазы обновлять handoff, отчёт, артефакты и следующий единственный шаг.
