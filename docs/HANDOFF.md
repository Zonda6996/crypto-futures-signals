# Project handoff

Обновлено: 21 августа 2026 года.

## Где продолжать

- Репозиторий: `Zonda6996/crypto-futures-signals`
- Ветка: `hypothesis-analysis-results`
- Roadmap: [`docs/roadmap.md`](./roadmap.md)
- Phase 1: [`reports/PHASE1_AUDIT.md`](../reports/PHASE1_AUDIT.md)
- Phase 2: [`reports/PHASE2_WALK_FORWARD.md`](../reports/PHASE2_WALK_FORWARD.md)
- Phase 4: [`reports/PHASE4_ECONOMIC_MECHANISM.md`](../reports/PHASE4_ECONOMIC_MECHANISM.md)
- Машинный отчёт Phase 2: [`reports/phase2/walk-forward.json`](../reports/phase2/walk-forward.json)

Новый чат сначала читает этот файл, затем отчёты Phase 1/2/4 и roadmap.

## Цель

Искать воспроизводимый edge для crypto perpetual futures небольшими фазами. Не выдавать положительный исторический результат за подтверждённую стратегию; учитывать исполнение BingX, funding, multiple testing и закрытый holdout.

## Текущий кандидат

Статус: **положительный walk-forward OOS; устойчивость и edge не подтверждены; к TEST не допущен**.

- ETHUSDT perpetual, long, 1h;
- `vwap_distance_24` в верхнем квартиле прошлого calibration-окна;
- BTC в медвежьем 24h-режиме;
- высокая волатильность относительно медианы прошлого calibration-окна;
- stop 1,5 ATR, take 2 ATR, максимум 24 часа;
- вход на open следующей свечи.

## Статус фаз

- Phase 1 завершена: аудит исполнения, причинности, данных и TRAIN-only calibration.
- Phase 2 завершена: anchored/rolling walk-forward только внутри TRAIN+VALIDATION.
- Phase 3 отсутствует и не считается завершённой.
- Phase 4 завершена: простой специфический 24h continuation-механизм не подтверждён.
- Закрытый TEST ни в одной из работ не оценивался.

## Результат Phase 2

Использованы только индексы `[0, 35059)`; TEST начинается с `35059`. Параметры кандидата и cost 0,10% round trip не менялись. В каждом окне на прошлом калибровались только quantile threshold и volatility median. Проверены четыре полных OOS-окна по 5 250 часов после initial/trailing history 14 000 часов.

Anchored:

- 42 сделки;
- expectancy `+0,221R`;
- total `+9,279R`;
- PF `1,602`;
- max drawdown `−3,152R`;
- 3 из 4 окон положительны.

Rolling:

- 75 сделок;
- expectancy `+0,086R`;
- total `+6,476R`;
- PF `1,195`;
- max drawdown `−5,756R`;
- 2 из 4 окон положительны.

Положительный объединённый OOS зафиксирован в обеих схемах. Но 2022 отрицателен, основная прибыль приходится на 2024, а rolling без лучших пяти сделок даёт `−0,044R`. Поэтому результат положительный, но концентрированный и недостаточный для TEST.

## Связь с Phase 4

Phase 4 показала отсутствие специфического положительного 24h drift: средний gross 24h return полного сигнала `−0,018%`, сравнение с главным контролем `−0,547` п.п. Это совместимо с Phase 2: возможный эффект может быть path-dependent и связан с stop/take барьерами, а не с простым 24h continuation.

## Cost model BingX

- 2,5 bps на сторону = 0,05% round trip;
- 5 bps на сторону = 0,10% round trip;
- 0,12% — реалистичная надбавка slippage;
- 0,16% — stress, не единственный baseline.

## Как воспроизвести

```bash
python3 -m unittest discover -s tests -v
python3 -m research.phase2_walk_forward
python3 -m research.phase4_mechanism
```

Market cache скачивается в `data/cache/` и исключён из Git.

## Ограничения

- кандидат появился после широкого перебора; selection bias остаётся;
- Phase 3 robustness ещё не выполнена;
- результаты концентрированы в 2024 и лучших сделках;
- в ранних OOS-окнах мало сделок;
- economic mechanism не подтверждён на 24h;
- фактические BingX fills отсутствуют;
- TEST запрещено открывать на следующей фазе.

## Ровно один следующий шаг

**Выполнить Phase 3 robustness замороженного кандидата только на TRAIN+VALIDATION.**

Заранее проверить costs 0,05%/0,10%/0,12%/0,16%, разумную чувствительность к границам walk-forward окон, удаление лучших сделок и карту соседних параметров как диагностику устойчивости. Не выбирать новую лучшую комбинацию и не открывать TEST. После Phase 3 зафиксировать отдельное решение: отказаться от версии или разрешить единственное открытие TEST в следующей фазе.

## Правила для следующих чатов

- работать только в `hypothesis-analysis-results`, не пушить в `main`;
- делать одну фазу за раз;
- не переименовывать положительный walk-forward в подтверждённый edge;
- не оптимизировать текущего кандидата в Phase 3;
- не открывать TEST до отдельного явного решения после Phase 3;
- в конце каждой фазы обновлять handoff, отчёт, артефакты и следующий единственный шаг.
