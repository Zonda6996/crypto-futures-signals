# Project handoff

Обновлено: 21 августа 2026 года.

## Где продолжать

- Репозиторий: `Zonda6996/crypto-futures-signals`
- Ветка: `hypothesis-analysis-results`
- Roadmap: [`docs/roadmap.md`](./roadmap.md)
- Phase 1: [`reports/PHASE1_AUDIT.md`](../reports/PHASE1_AUDIT.md)
- Phase 4: [`reports/PHASE4_ECONOMIC_MECHANISM.md`](../reports/PHASE4_ECONOMIC_MECHANISM.md)
- Машинный отчёт Phase 4: [`reports/phase4/mechanism.json`](../reports/phase4/mechanism.json)

Новый чат сначала читает этот файл, затем отчёты Phase 1/4 и roadmap.

## Цель

Искать воспроизводимый edge для crypto perpetual futures небольшими фазами. Не выдавать удачный исторический участок за стратегию; учитывать исполнение BingX, funding, multiple testing и закрытый holdout.

## Текущий кандидат

Статус: **исследовательский кандидат; экономический механизм не подтверждён; к TEST не допущен**.

- ETHUSDT perpetual, long, 1h;
- цена выше 24h VWAP: `vwap_distance_24` в верхнем квартиле TRAIN;
- BTC в медвежьем 24h-режиме;
- высокая волатильность относительно медианы TRAIN;
- stop 1,5 ATR, take 2 ATR, максимум 24 часа;
- вход на open следующей свечи.

## Статус фаз

- Phase 1 завершена: аудит исполнения, причинности, данных и TRAIN-only calibration.
- Phase 2 отсутствует в этой ветке и **не считается завершённой**.
- Phase 3 отсутствует в этой ветке и **не считается завершённой**.
- Phase 4 завершена после явного разрешения пользователя пропустить отсутствующие Phase 2/3.
- Закрытый TEST ни в одной из этих работ не оценивался.

## Что сделано в Phase 4

1. Использованы только TRAIN+VALIDATION, индексы `[0, 35059)`; TEST начинается с `35059`.
2. Замороженные параметры и TRAIN calibration не менялись.
3. Построены conditional paths через 1/4/8/12/24 часа с входом на следующем open.
4. Чтобы уменьшить зависимость перекрывающихся путей, в каждой когорте оставлялось не более одного события каждые 25 часов.
5. Полный сигнал сравнивался с `BTC bear + high vol`, но без ETH VWAP extension, а также с extension в других BTC regimes и широкими baseline-когортами.
6. Проверены abnormal volume, taker imbalance, relative strength, funding и вклад stop/take/time exits.
7. Добавлены воспроизводимый runner, JSON-артефакт и два unit-теста helpers.

## Результат Phase 4

Для 153 неперекрывающихся событий полного сигнала gross forward return:

- 8h: `+0,175%`, positive rate `56,9%`;
- 12h: `+0,321%`, positive rate `55,6%`;
- 24h: `−0,018%`, positive rate `52,3%`.

На 24 часах полный сигнал уступает контролю `BTC bear + high vol, ETH ниже frozen VWAP threshold` на `−0,547` процентного пункта. Bootstrap 95% CI `−1,652…+0,509` п.п. включает ноль; вероятность положительной разницы `15,9%`.

Состояние сигнала похоже на относительную силу ETH во время падения BTC (`relative_strength_24` в среднем `+1,886%`), но не на однозначный агрессивный приток: средний taker imbalance отрицателен, abnormal volume неоднороден, положительный funding является drag для long.

Исходные barrier exits на объединённом TRAIN+VALIDATION при 0,10% cost дают 185 сделок, `+0,0886R` expectancy и PF `1,127`, но обычный 95% CI expectancy пересекает ноль. Положительный trade-level результат не подтверждает простой 24h drift и может быть path-dependent; не переобучать эту интерпретацию постфактум.

## Решение

Экономический механизм `ETH выше VWAP в BTC-bear/high-vol режиме → специфическое продолжение на 24h` **не подтверждён**. Это не доказательство отрицательного edge, но оснований открывать TEST или начинать paper trading нет.

## Cost model BingX

`CostModel.taker_fee_bps` — ставка за одну сторону исполнения:

- 2,5 bps на вход + 2,5 bps на выход = 0,05% round trip;
- 5 bps на вход + 5 bps на выход = 0,10% round trip.

0,05%/0,10% остаются основными сценариями; 0,16% — только stress. Фактический slippage позже измерять по fills.

## Как воспроизвести

```bash
python3 -m unittest discover -s tests -v
python3 -m research.phase4_mechanism
```

Market cache скачивается в `data/cache/` и исключён из Git.

## Ограничения

- Phase 2 walk-forward и Phase 3 robustness не воспроизведены в этой ветке.
- Кандидат появился после широкого перебора; selection bias остаётся.
- Bootstrap Phase 4 описательный, а не causal/multiple-testing-adjusted proof.
- Контроли не являются полностью matched causal experiment.
- Point-in-time-safe полная история open interest не использована.
- Фактические BingX fills отсутствуют.
- TEST запрещено открывать на следующей фазе.

## Ровно один следующий шаг

**Выполнить пропущенную Phase 2: anchored/rolling walk-forward замороженного кандидата только внутри TRAIN+VALIDATION.**

В каждом окне калибровать threshold/volatility только на прошлом, применять к следующему окну, соединить OOS-сделки и сохранить результаты по окнам/годам, концентрацию прибыли и OOS equity в R. Параметры не менять, TEST не открывать. Если объединённый OOS walk-forward не положителен и не распределён по окнам, зафиксировать отказ от текущей версии без открытия TEST.

## Правила для следующих чатов

- Работать только в `hypothesis-analysis-results`, не пушить в `main`.
- Делать одну фазу за раз.
- Не считать Phase 2/3 выполненными только из-за номера Phase 4.
- Не оптимизировать параметры текущего кандидата в Phase 2.
- Не открывать TEST до отдельного явного решения.
- Не использовать 0,16% как единственный baseline.
- В конце каждой фазы обновлять handoff, отчёт, артефакты и следующий единственный шаг.
