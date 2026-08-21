# Project handoff

Обновлено: 21 августа 2026 года.

## Где продолжать

- Репозиторий: `Zonda6996/crypto-futures-signals`
- Рабочая ветка: `crypto-futures-signals` (содержит результаты Phase 1–4 после rebase на remote)
- Roadmap: [`docs/roadmap.md`](./roadmap.md)
- Phase 1: [`reports/PHASE1_AUDIT.md`](../reports/PHASE1_AUDIT.md)
- Оригинальная Phase 2: [`reports/PHASE2_WALK_FORWARD.md`](../reports/PHASE2_WALK_FORWARD.md)
- Дополнительный повтор Phase 2: [`reports/PHASE2_WALK_FORWARD_REPEAT.md`](../reports/PHASE2_WALK_FORWARD_REPEAT.md)
- Оригинальная Phase 3: [`reports/PHASE3_PARAMETER_STABILITY.md`](../reports/PHASE3_PARAMETER_STABILITY.md)
- Дополнительная повторная robustness-проверка: [`reports/PHASE3_ROBUSTNESS.md`](../reports/PHASE3_ROBUSTNESS.md)
- Phase 4: [`reports/PHASE4_ECONOMIC_MECHANISM.md`](../reports/PHASE4_ECONOMIC_MECHANISM.md)

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
```

Market cache скачивается в `data/cache/` и исключён из Git.

## Ограничения

- кандидат появился после широкого перебора; selection bias остаётся;
- strict Phase 3 pass не пройден из-за top-5 concentration rolling;
- результат по периодам неравномерен и концентрирован в 2024;
- economic mechanism не подтверждён на 24h;
- карта соседей однофакторная и не является новым поиском optimum;
- фактические BingX fills отсутствуют;
- TEST запрещено открывать без отдельного явного решения.

## Ровно один следующий шаг

**Принять отдельное решение по frozen candidate: остановить текущую версию либо явно разрешить единственное открытие закрытого TEST в следующей фазе.**

Если открытие разрешено, до просмотра зафиксировать критерий успеха и выполнить один прогон без изменения параметров. Если разрешения нет — TEST не трогать и текущую версию не продвигать в paper trading.

## Правила для следующих чатов

- не пушить в `main`;
- делать одну фазу за раз;
- не называть положительный walk-forward подтверждённым edge;
- не выбирать новый candidate из Phase 3 neighbor map;
- не открывать TEST до отдельного явного решения;
- в конце каждой фазы обновлять handoff, отчёт, артефакты и следующий единственный шаг.
