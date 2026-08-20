# Project handoff

Обновлено: 20 августа 2026 года.

## Где продолжать

- Репозиторий: `Zonda6996/crypto-futures-signals`
- Ветка: `hypothesis-analysis-results`
- Roadmap: [`docs/roadmap.md`](./roadmap.md)
- Phase 1: [`reports/PHASE1_AUDIT.md`](../reports/PHASE1_AUDIT.md)
- Phase 2: [`reports/PHASE2_WALK_FORWARD.md`](../reports/PHASE2_WALK_FORWARD.md)
- Phase 3: [`reports/PHASE3_PARAMETER_STABILITY.md`](../reports/PHASE3_PARAMETER_STABILITY.md)
- Машинный отчёт Phase 3: [`reports/phase3/parameter-map.json`](../reports/phase3/parameter-map.json)

Новый чат сначала читает этот файл, затем отчёты Phase 1–3 и roadmap.

## Цель

Искать воспроизводимый edge для crypto perpetual futures небольшими фазами. Не выдавать удачный исторический участок за стратегию; учитывать исполнение BingX, funding, multiple testing и закрытый holdout.

## Текущий кандидат

Статус: **прошёл Phase 2 walk-forward и Phase 3 parameter stability, но не готов к торговле**.

- ETHUSDT perpetual, long, 1h;
- `vwap_distance_24` в верхнем квартиле прошлого calibration-окна;
- BTC в медвежьем 24h-режиме;
- `rv_24` выше медианы прошлого calibration-окна;
- stop 1,5 ATR, take 2 ATR, максимум 24 часа;
- сигнал на закрытой свече, вход на open следующей свечи.

## Что сделано

### Phase 1

- Восстановлен Python research engine и добавлены тесты причинности/исполнения.
- Исправлена утечка: threshold и median volatility больше не вычисляются на VALIDATION.
- Сохранены полные trade logs и четыре cost-сценария.
- Clean VALIDATION при 0,10%: 32 сделки, +0,284R expectancy, +9,09R, PF 1,87; 95% CI пересекает ноль.

### Phase 2

- Проверены anchored и rolling схемы 12/3 и 18/6 месяцев только внутри TRAIN+VALIDATION.
- Calibration каждого окна использует только прошлое; параметры кандидата не менялись.
- OOS-сделки соединены с глобальным запретом пересечения позиций.
- Все четыре схемы положительны при расходах 0,05%, 0,10%, 0,12% и 0,16%.

### Phase 3

- Добавлен `research/phase3_parameter_map.py` и 5 unit-тестов; всего проходит 25 тестов.
- Проверена заранее заданная сетка 4×4×4×4 = 256 точек: VWAP 12/24/48/72h, stop 1,2/1,5/1,8/2,0 ATR, take 1,5/2/2,5/3 ATR, holding 12/24/36/48h.
- Каждый VWAP-threshold и `rv_24` median заморожены на TRAIN; оценка выполнена только на VALIDATION.
- Симулятор обрезан индексом 35 059, где начинается sealed TEST.
- Не выбиралась лучшая точка; оценивалась форма поверхности и заранее определённый локальный кластер.

## Главный результат Phase 2 при 0,10% round trip

| Схема | Сделок | Expectancy | Total R | PF | Max DD | Прибыльных окон | Best 5 / Total R |
|---|---:|---:|---:|---:|---:|---:|---:|
| anchored 12/3 | 57 | +0,197R | +11,25R | 1,50 | −3,82R | 58,3% | 58,1% |
| rolling 12/3 | 106 | +0,092R | +9,80R | 1,21 | −6,31R | 58,3% | 66,6% |
| anchored 18/6 | 44 | +0,299R | +13,14R | 1,93 | −3,15R | 100,0% | 49,7% |
| rolling 18/6 | 79 | +0,105R | +8,28R | 1,24 | −5,35R | 80,0% | 78,8% |

## Главный результат Phase 3

| Полные расходы | Положительных точек сетки | Медианный expectancy сетки | Положительных точек локального кластера | Медианный expectancy кластера |
|---|---:|---:|---:|---:|
| 0,05% | 94,9% | +0,176R | 9/9 | +0,268R |
| 0,10% | 90,2% | +0,153R | 9/9 | +0,246R |
| 0,12% | 88,7% | +0,145R | 9/9 | +0,237R |
| 0,16% | 83,6% | +0,124R | 9/9 | +0,219R |

Baseline 24h / 1,5 / 2 / 24 при 0,10%: 32 сделки, +0,284R expectancy, +9,09R, PF 1,87, max DD −3,15R. VWAP 12h заметно слабее, но остаётся положительным в медиане; 24–72h образуют широкую положительную область.

## Интерпретация

Parameter map не показывает одиночного узкого пика: исходная точка окружена положительными соседями, и вывод сохраняется во всех cost-сценариях. Это усиливает кандидата, но не доказывает edge:

- clean VALIDATION baseline содержит только 32 сделки;
- Phase 2 rolling PF при 0,10% лишь 1,21–1,24;
- лучшие пять baseline-сделок дают 71,5% total R;
- исходный кандидат возник после широкого перебора;
- Phase 3 использует уже просмотренную VALIDATION как диагностическую поверхность;
- экономический механизм и фактические cost/slippage BingX ещё не подтверждены.

Закрытый TEST: **не открыт**. В Phase 3 записано `test_opened: false`; evaluation заканчивается индексом 35 059, с которого sealed TEST только начинается.

## Как воспроизвести

```bash
python3 -m unittest discover -s tests -v
python3 -m research.phase2_walk_forward
python3 -m research.phase3_parameter_map
```

Market cache находится в `data/cache/` и исключён из Git.

## Артефакты Phase 3

- `reports/phase3/parameter-map.json` — машинный отчёт и агрегации;
- `reports/phase3/parameter-map.csv` — все 1 024 оценки: 256 точек × 4 cost-сценария;
- `reports/PHASE3_PARAMETER_STABILITY.md` — метод, результаты и ограничения;
- `research/phase3_parameter_map.py` — runner;
- `tests/test_phase3.py` — причинность VWAP, полнота сетки и cluster-rule.

## Ровно один следующий шаг

**Phase 4: заранее описанная проверка экономического механизма текущего сигнала только внутри TRAIN+VALIDATION.**

Не меняя параметры baseline, проверить ограниченный набор объяснений: ETH/BTC relative strength, BTC momentum 1/4/12/24h, abnormal volume и доступные funding-признаки. Использовать их для объяснения и falsification через заранее заданные срезы, а не для поиска новой лучшей стратегии. TEST не открывать.

## Правила для следующих чатов

- Работать только в `hypothesis-analysis-results`, не пушить в `main`.
- Делать одну фазу за раз.
- Не объявлять Phase 2/3 доказательством готовности к торговле.
- Не выбирать лучшую точку Phase 3 как новую конфигурацию.
- Не открывать TEST до отдельного явного решения.
- Не использовать 0,16% как единственный baseline.
- В конце каждой фазы обновлять handoff, отчёт, артефакты и ровно один следующий шаг.
