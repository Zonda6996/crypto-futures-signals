# Project handoff

Обновлено: 22 августа 2026 года.

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
- Immutable TEST-opening memo: [`docs/TEST_OPENING_MEMO.md`](./TEST_OPENING_MEMO.md)
- Pre-TEST/hash allowlist: [`docs/test-opening-hashes.json`](./test-opening-hashes.json)
- План независимого исследования альткоинов для нового чата: [`docs/ALTCOIN_RESEARCH_NEXT_CHAT.md`](./ALTCOIN_RESEARCH_NEXT_CHAT.md)
- Утверждённый план нового multi-timeframe research engine: [`docs/ALTCOIN_RESEARCH_ENGINE_PROTOCOL.md`](./ALTCOIN_RESEARCH_ENGINE_PROTOCOL.md)
- Готовый handoff для его документационной Phase 0: [`docs/ALTCOIN_RESEARCH_ENGINE_NEXT_CHAT.md`](./ALTCOIN_RESEARCH_ENGINE_NEXT_CHAT.md)
- Frozen Phase 0 protocol нового engine: [`docs/ALTCOIN_MULTITF_FROZEN_PROTOCOL.md`](./ALTCOIN_MULTITF_FROZEN_PROTOCOL.md)
- Frozen altcoin protocol: [`docs/ALTCOIN_PROTOCOL.md`](./ALTCOIN_PROTOCOL.md)
- Altcoin Phase A audit: [`reports/ALTCOIN_PHASE_A_DATA_AUDIT.md`](../reports/ALTCOIN_PHASE_A_DATA_AUDIT.md)
- Altcoin frozen TRAIN/VALIDATION result: [`reports/ALTCOIN_PHASE_B_TRAIN_VALIDATION.md`](../reports/ALTCOIN_PHASE_B_TRAIN_VALIDATION.md)
- Compact multi-TF protocol: [`docs/ALTCOIN_MULTITF_COMPACT_PROTOCOL.md`](./ALTCOIN_MULTITF_COMPACT_PROTOCOL.md)
- Compact data-phase result: [`reports/ALTCOIN_MULTITF_COMPACT_DATA_PHASE.md`](../reports/ALTCOIN_MULTITF_COMPACT_DATA_PHASE.md)

## Новый altcoin Phase A status

Protocol `ALT-XSMOM-001-A` зафиксирован: cross-sectional long/short, point-in-time Top 30 и HOLDOUT с `2026-01-01`. Строгая Phase A завершена с verdict **STOP**: полного датированного pre-2026 lifecycle registry Binance USD-M perpetuals с delisted-контрактами нет; current roster создал бы survivorship bias. По явному решению владельца зафиксирован отдельный exploratory amendment `ALT-XSMOM-001-B`: вместо Top 30 используется неизменяемая корзина из 10 заранее выбранных ликвидных контрактов — `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`, `ADAUSDT`, `DOGEUSDT`, `LINKUSDT`, `LTCUSDT`, `AVAXUSDT`, `DOTUSDT`. Это осознанно допускает survivorship/selection bias, поэтому будущий результат будет exploratory и не отменит Phase A STOP. HOLDOUT не загружался; signal/PnL и parameter search ещё не запускались.
- Единственный TEST result/audit: [`reports/private/test-opening/result.json`](../reports/private/test-opening/result.json)

## Altcoin Phase B frozen TRAIN/VALIDATION status

Exploratory fixed-basket experiment `ALT-XSMOM-001-B` завершён с **FAIL / STOP**. Pre-HOLDOUT audit прошёл gate: максимум одновременно eligible активов — 10; все series заканчиваются `2025-12-31T23:00:00Z`, HOLDOUT не читался. Frozen calendar: TRAIN `[2020-05-05, 2024-04-20)`, VALIDATION `[2024-04-20, 2026-01-01)`. TRAIN-only selection выбрал `30d momentum / 24h rebalance`; на единственной VALIDATION при 0,12% получены net Sharpe `−0,817`, compounded return `−35,90%`, max drawdown `−46,78%`, bootstrap CI95 `[−2,449; +0,632]`. При 0,20% результат `−60,99%`; concentration limit также нарушен. Полные ledgers и machine artifacts находятся в `reports/altcoin-phase-b/`.

Это только **exploratory fixed-basket evidence with survivorship/selection bias**. Нельзя переотбирать другую grid point по VALIDATION, менять корзину, открывать HOLDOUT, возвращаться к старому ETH TEST или переходить к paper/live trading.

Read-only post-mortem завершён: cost drag превысил VALIDATION gross effect, short leg был отрицателен уже gross, а frozen concentration limit нарушался во всех active periods. Подробности: [`reports/ALTCOIN_PHASE_B_POSTMORTEM.md`](../reports/ALTCOIN_PHASE_B_POSTMORTEM.md).

Зафиксированные следующие фазы:
1. **Фаза 0 — закрытие:** `ALT-XSMOM-001-B` окончательно FAIL / STOP (завершена).
2. **Фаза 1 — read-only post-mortem:** диагностика существующих TRAIN/VALIDATION ledgers без parameter search (завершена).
3. **Gate 1 — owner decision:** владелец разрешил только документационную Фазу 2 (пройден).
4. **Фаза 2 — новый protocol:** frozen `ALT-LOMOM-002-A` создан до реализации и расчётов (завершена).
5. **Фаза 3 — реализация и TRAIN (DONE):** реализован ровно один preregistered вариант; DEVELOPMENT/TRAIN diagnostic получил PASS. Отчёт: [`reports/ALTCOIN_LOMOM_PHASE3_TRAIN.md`](../reports/ALTCOIN_LOMOM_PHASE3_TRAIN.md).
6. **Фаза 4 — prospective VALIDATION:** `[2026-09-01, 2027-09-01)`, один механический gate без retuning (не начата; отдельное разрешение обязательно).
7. **Фаза 5 — paper trading:** только после уверенного PASS и отдельного разрешения; live — отдельное решение (не начата).

Новый frozen protocol: [`docs/ALTCOIN_LONG_ONLY_PROTOCOL.md`](./ALTCOIN_LONG_ONLY_PROTOCOL.md). Это adaptive low-turnover long-only гипотеза на той же fixed basket: `30d` momentum, top 4 по 25%, weekly rebalance, causal portfolio-vol scaling до 20% с multiplier `[0,1]`, realistic/stress costs 0,12%/0,20%. Grid search запрещён.

Все данные `< 2026-01-01` считаются DEVELOPMENT/TRAIN, а не новым OOS. Новый prospective VALIDATION — `[2026-09-01, 2027-09-01)`, новый sealed HOLDOUT начинается `2027-09-01`. Старый HOLDOUT не открывался и не переопределён.

**Текущая точка остановки baseline:** Фаза 3 DONE. TRAIN diagnostic: PASS — Sharpe `1,1508`, compounded return `+270,37%` при 0,12%, stress `+254,18%`, max drawdown `−28,00%`, bootstrap CI95 `[0,2308; 2,0609]`, 0 нарушений; ledger reconciliation PASS. Это contaminated DEVELOPMENT/TRAIN evidence на fixed basket с survivorship/selection bias, не prospective подтверждение. `ALT-LOMOM-002-A` остаётся неизменяемым baseline; VALIDATION и любое изменение baseline запрещены.

**`ALT-MULTITF-003` закрыт как невосстановимый:** его Phase 1A raw payload и machine manifests не были закоммичены и утрачены вместе с прежним sandbox; исторический отчёт не переписывается и старые хеши не выдаются за восстановленные данные.

**Compact replacement `ALT-MULTITF-004` — PHASE 2 DONE:** до acquisition заморожены 40 top-current-liquidity USDT perpetual altcoins (BTC/ETH исключены). Development `[2020-01-01, 2026-01-01)` содержит `3 291` raw files / `568 466 246` bytes; исторический data-phase manifest SHA-256 `224f6449…`. Нормализованы `14 276 432` строк 5m и `168 371` funding; `BTWUSDT` остаётся во frozen roster без history. Owner-approved Phase 2 реализовала deterministic causal features/signals для short/medium/long TF groups, publication-time funding alignment и eligibility-before-ranking. Focused leakage tests PASS; parameter search, portfolio execution, PnL, backtest и holdout reads отсутствуют. Ignored dataset закреплён в SHA-256 verified public Blob; restore metadata — [`docs/altcoin-multitf-004-blob.json`](./altcoin-multitf-004-blob.json), restore CLI — `python3 -m scripts.restore_altcoin_multitf_004 --root data`. Spec: [`docs/ALTCOIN_MULTITF_COMPACT_PHASE2_SPEC.md`](./ALTCOIN_MULTITF_COMPACT_PHASE2_SPEC.md). Текущая точка — STOP перед отдельным strategy-evaluation gate.

Новый чат сначала читает этот файл, новый frozen protocol, итоговый Phase B report, post-mortem и roadmap.

## Правило коммуникации после каждой фазы

После завершения каждой фазы обязательно сразу дать владельцу простое объяснение без исследовательского жаргона: **что сделали, какой получили результат, что это означает на практике, прошла ли фаза PASS/FAIL и какой следующий шаг разрешён или запрещён**. Технические метрики можно привести следом, но они не заменяют человеческий итог. Нельзя ограничиваться сообщением о commit/push или статусом `DONE`.

## Цель

Искать воспроизводимый edge для crypto perpetual futures небольшими фазами. Не выдавать положительный исто��ический результат за подтверждённую стратегию; учитывать исполнение BingX, funding, multiple testing и закрытый holdout.

## Текущий кандидат

Статус: **старый frozen candidate окончательно отклонён: единственный TEST 2025 завершился FAIL; повторное открытие и настройка по TEST запрещены**.

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
- Immutable TEST-opening memo и SHA-256 allowlist подготовлены на frozen research commit `81f5ea590edbc04fadce762452801c1d365470d0`; integrity/one-time gate добавлены без изменения стратегии.
- Владелец дал точное разрешение; TEST был открыт один раз. Verdict: **FAIL** — 32 сделки, expectancy `−0,160R`, total `−5,135R`, CI95 `[−0,495R; +0,186R]`, max drawdown `−5,640R`.
- Право открытия TEST израсходовано. Повторный запуск, retuning и использование 2025 TEST для новой версии гипотезы запрещены.

## Результаты Phase 2

Оригинальная Phase 2: все четыре заданные walk-forward-схемы дали положительный объединённый OOS. Следующие числа относятся только к дополнительному повтору Phase 2 при 0,10% round trip:

- anchored: 42 сделки, expectancy `+0,221R`, total `+9,279R`, PF `1,602`, 3/4 положительных окон;
- rolling: 75 сдело��, expectancy `+0,086R`, total `+6,476R`, PF `1,195`, 2/4 положительных окон.

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

Предварительно заданный strict rule требовал положительный frozen результ��т после удаления top-5 в обеих схемах. Требование не выполнено, поэтому `strict pass = false`. Не выбирать новый лучший вариант из карты соседей.

## Дополнительная M15/M30 robustness-проверка

При механическом сохранении часовых горизонтов M30 и M15 положительны на VALIDATION при 0,10%: соответственно `+2,675R` и `+4,233R`. Но без top-5 результаты равны `−3,791R` и `−2,173R`; при 0,16% M15 также становится отрицательным (`−0,238R`). З��ранее заданный строгий критерий поддержки не пройден; параметры не переотбирались, TEST закрыт.

## Отдельная regime/concentration-диагностика

Диагностика выполнена отдельно от Phase 2–4 на полном pre-TEST TRAIN+VALIDATION-срезе 2021–2024 при frozen-параметрах и расходах 0,10%. Это опи��ательный анализ конц��нтрации, не новая OOS-оценка. BTC-режимы размече��ы каузально: trailing 90-day return и trailing 30-day realized volatility; пороги — expanding median только предшествующих валидных наблюдений.

- 1h: 185 сделок, `+16,387R`; top-5 = 40,1% total, без top-5 `+9,808R`.
- M30: 264 сделки, `+7,926R`; top-5 = 83,0%, без top-5 `+1,348R`.
- M15: 401 сделка, `+0,654R`; top-5 = 1003,3%, без top-5 `−5,910R`.
- Leave-one-year-out и leave-one-regime-out сохранены в отдельных JSON; сделки — в отдельных CSV.
- Ранние сделки без достаточной 90-day/past-threshold истории выделены как `insufficient_history`, а не классифицированы задним числом.
- TEST с `2025-01-01` не загру��ался, не анализировался и не открывался.

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

Важная отрицательная диагностика, которая не входила в семь verdict-кри��ериев: дополнительная задержка входа на один 1h-бар дала `−2,358R`. Максимальный период без нового equity high — около 970 дн��й. Поэтому PASS разрешает только подготовить immutable TEST-opening memo, но не означает подтверждённый edge и не разрешает открывать TEST.

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

**Остановиться после FAIL frozen TRAIN/VALIDATION `ALT-XSMOM-001-B`.**

Не выбирать другую конфигурацию из уже просмотренной grid, не менять frozen basket и не открывать HOLDOUT с `2026-01-01`. Любая будущая новая гипотеза требует отдельного owner decision, нового protocol ID и нового будущего sealed holdout; текущая версия не допускается к paper/live trading.

## Правила для следующих чатов

- не пушить в `main`;
- делать одну фазу за раз;
- не называть положительный walk-forward подтверждённым edge;
- не выбирать новый candidate из Phase 3 neighbor map;
- старый TEST 2025 уже открыт и израсходован: никогда не запускать повторно и не использовать для retuning;
- в конце к��ждой фазы обновлять handoff, отчёт, артефакты и следующий единственный шаг.
