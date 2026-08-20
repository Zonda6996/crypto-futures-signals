# Project handoff

Обновлено: 20 августа 2026 года.

## Где продолжать

- Репозиторий: `Zonda6996/crypto-futures-signals`
- Ветка: `hypothesis-analysis-results`
- Roadmap: [`docs/roadmap.md`](./roadmap.md)
- Phase 1: [`reports/PHASE1_AUDIT.md`](../reports/PHASE1_AUDIT.md)
- Машинный отчёт: [`reports/phase1/audit.json`](../reports/phase1/audit.json)

Новый чат сначала читает этот файл, затем Phase 1 и roadmap.

## Цель

Искать воспроизводимый edge для crypto perpetual futures небольшими фазами. Не выдавать удачный исторический участок за стратегию; учитывать исполнение BingX, funding, multiple testing и закрытый holdout.

## Текущий кандидат

Статус: **лучший исследовательский кандидат, не готов к торговле**.

- ETHUSDT perpetual, long, 1h;
- цена выше 24h VWAP: `vwap_distance_24` в верхнем квартиле TRAIN;
- BTC в медвежьем 24h-режиме;
- высокая волатильность относительно медианы TRAIN;
- stop 1,5 ATR, take 2 ATR, максимум 24 часа;
- вход на open следующей свечи.

## Что сделано в Phase 1

1. В репозиторий возвращены `research/*` и `tests/*`; временный архив больше не нужен.
2. Добавлены 14 проходящих unit-тестов причинности, исполнения, признаков и selection boundaries.
3. Сохранены полные trade logs TRAIN и VALIDATION с gross/net return, cost, funding, initial risk, R, MAE, MFE и причиной выхода.
4. Проверены BTC/ETH данные: по 43 824 часовых свечи, gaps 0, duplicates 0, invalid OHLC 0.
5. Закрытый TEST не оценивался.

## Важная найденная ошибка

Первый диагностический прогон рассчитывал threshold признака и median volatility отдельно на VALIDATION. Это не прямой price look-ahead, но утечка распределения проверочного периода.

Теперь обе величины вычисляются только на TRAIN и замораживаются:

- `vwap_distance_24 threshold = 0.0112126205`;
- `rv_24 median = 0.0318858528`.

Исправлен не только Phase 1 script, но и общий `research/search.py`/`research/pipeline.py`: VALIDATION и будущий TEST получают TRAIN calibration.

## Актуальный результат

После исправления при полном расходе 0,10%:

### TRAIN

- 153 сделки;
- expectancy `+0,0477R`;
- total `+7,29R`;
- PF `1,048`;
- max drawdown `−8,86R`;
- compounded return около `+0,61%`;
- 95% CI пересекает ноль.

### VALIDATION

- 32 сделки;
- expectancy `+0,284R`;
- total `+9,09R`;
- PF `1,90`;
- win rate `59,4%`;
- max drawdown `−3,15R`;
- compounded return `+24,69%`;
- 95% CI: `−0,177%…+1,626%`, пересекает ноль.

Предыдущие 43 сделки / +12,3R больше не являются актуальным clean baseline из-за перекалибровки на VALIDATION.

## Cost model BingX

`CostModel.taker_fee_bps` — ставка за одну сторону. Поэтому:

- 2,5 bps на вход + 2,5 bps на выход = 0,05% round trip;
- 5 bps на вход + 5 bps на выход = 0,10% round trip.

Phase 1 сохраняет сценарии 0,05%, 0,10%, 0,12% и 0,16%. Для небольшого депозита 0,05%/0,10% считаются основными; slippage не завышается и должен позже измеряться по фактическим fills.

## Как воспроизвести

```bash
python3 -m unittest discover -s tests -v
python3 -m research.phase1_audit
```

Market cache скачивается в `data/cache/` и исключён из Git.

## Ограничения

- VALIDATION содержит только 32 сделки.
- Его доверительный интервал пересекает ноль.
- TRAIN намного слабее VALIDATION.
- Sharpe в отчёте нельзя считать главным показателем из-за редких и неодинаковых по длительности сделок.
- Кандидат возник после широкого перебора; multiple-testing риск остаётся.
- TEST запрещено открывать на следующей фазе.

## Ровно один следующий шаг

**Phase 2: anchored/rolling walk-forward только внутри доступных TRAIN+VALIDATION данных.**

Нужно разбить историю на последовательные окна, в каждом калибровать threshold/volatility только на прошлом, применять к следующему окну и соединить out-of-sample сделки. Сохранить результаты по окнам и годам, концентрацию прибыли и единую OOS equity в R. Параметры кандидата не менять, TEST не открывать.

## Правила для следующих чатов

- Работать только в `hypothesis-analysis-results`, не пушить в `main`.
- Делать одну фазу за раз.
- Не оптимизировать параметры текущего кандидата в Phase 2.
- Не открывать TEST до отдельного явного решения.
- Не использовать 0,16% как единственный baseline.
- В конце каждой фазы обновлять этот handoff, отчёт, артефакты и следующий единственный шаг.
