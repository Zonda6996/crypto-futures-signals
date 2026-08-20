# Project handoff

Обновлено: 20 августа 2026 года.

## Где продолжать

- Репозиторий: `Zonda6996/crypto-futures-signals`
- Ветка: `hypothesis-analysis-results`
- Roadmap: [`docs/roadmap.md`](./roadmap.md)
- Phase 1: [`reports/PHASE1_AUDIT.md`](../reports/PHASE1_AUDIT.md)
- Phase 2: [`reports/PHASE2_WALK_FORWARD.md`](../reports/PHASE2_WALK_FORWARD.md)
- Машинный отчёт Phase 2: [`reports/phase2/walk-forward.json`](../reports/phase2/walk-forward.json)

Новый чат сначала читает этот файл, затем отчёты Phase 1/2 и roadmap.

## Цель

Искать воспроизводимый edge для crypto perpetual futures небольшими фазами. Не выдавать удачный исторический участок за стратегию; учитывать исполнение BingX, funding, multiple testing и закрытый holdout.

## Текущий кандидат

Статус: **прошёл Phase 2 walk-forward, но не готов к торговле**.

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
- Clean VALIDATION при 0,10%: 32 сделки, +0,284R expectancy, +9,09R, PF 1,90; 95% CI пересекает ноль.

### Phase 2

- Добавлен `research/phase2_walk_forward.py`.
- Проверены anchored и rolling схемы 12/3 и 18/6 месяцев только внутри TRAIN+VALIDATION.
- Calibration каждого окна использует только прошлое; параметры кандидата не менялись.
- OOS-сделки соединены с глобальным запретом пересечения позиций.
- Сохранены JSON, полный trade log, метрики по окнам и годам.
- Добавлены 6 тестов Phase 2; всего проходит 20 unit-тестов.

## Главный результат Phase 2 при 0,10% round trip

| Схема | Сделок | Expectancy | Total R | PF | Max DD | Прибыльных окон | Best 5 / Total R |
|---|---:|---:|---:|---:|---:|---:|---:|
| anchored 12/3 | 57 | +0,197R | +11,25R | 1,50 | −3,82R | 58,3% | 58,1% |
| rolling 12/3 | 106 | +0,092R | +9,80R | 1,21 | −6,31R | 58,3% | 66,6% |
| anchored 18/6 | 44 | +0,299R | +13,14R | 1,93 | −3,15R | 100,0% | 49,7% |
| rolling 18/6 | 79 | +0,105R | +8,28R | 1,24 | −5,35R | 80,0% | 78,8% |

Все четыре схемы положительны также при 0,05%, 0,12% и 0,16%. Rolling-схемы распределяют положительный результат между 2022, 2023 и 2024 годами, но имеют заметно более слабый PF и более глубокую просадку, чем anchored.

## Интерпретация

Walk-forward не уничтожил кандидата и уменьшил вероятность того, что clean VALIDATION был единственным удачным коротким режимом. Однако доказанного edge всё ещё нет:

- схемы содержат от 44 до 106 сделок;
- rolling PF при 0,10% лишь 1,21–1,24;
- лучшие пять сделок дают 58–79% total R;
- кандидат возник после широкого перебора, multiple-testing риск сохраняется;
- фактический cost/slippage BingX ещё нужно подтвердить fills.

Закрытый TEST: **не открыт**. В `walk-forward.json` записано `test_opened: false`; разрешённый диапазон заканчивается индексом 35 059, где sealed TEST только начинается.

## Как воспроизвести

```bash
python3 -m unittest discover -s tests -v
python3 -m research.phase2_walk_forward
```

Market cache находится в `data/cache/` и исключён из Git.

## Артефакты Phase 2

- `reports/phase2/walk-forward.json` — полный машинный отчёт;
- `reports/phase2/trades.csv` — объединённые OOS-сделки всех схем и расходов;
- `reports/phase2/windows.csv` — метрики по окнам;
- `reports/phase2/years.csv` — метрики по годам;
- `reports/PHASE2_WALK_FORWARD.md` — выводы фазы.

## Ровно один следующий шаг

**Phase 3: заранее зафиксированная карта устойчивости соседних параметров только внутри TRAIN+VALIDATION.**

Проверить VWAP 12/24/48/72h, stop 1,2/1,5/1,8/2,0 ATR, take 1,5/2/2,5/3 ATR и holding 12/24/36/48h как заранее заданную сетку. Цель — определить, образует ли текущая точка положительный кластер, а не выбрать новый исторический максимум. TEST не открывать.

## Правила для следующих чатов

- Работать только в `hypothesis-analysis-results`, не пушить в `main`.
- Делать одну фазу за раз.
- Не объявлять Phase 2 доказательством готовности к торговле.
- В Phase 3 не выбирать лучшую точку; оценивать форму и устойчивость кластера.
- Не открывать TEST до отдельного явного решения после Phase 3.
- Не использовать 0,16% как единственный baseline.
- В конце каждой фазы обновлять handoff, отчёт, артефакты и ровно один следующий шаг.
