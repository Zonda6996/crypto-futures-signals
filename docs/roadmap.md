# Roadmap поиска торгового edge

Дата фиксации: 22 августа 2026 года.

## Текущий статус

**ALT-MULTITF-005:** Public Blob release анонимно восстановлен и подтверждён по size/SHA-256, safe extraction и normalized manifest. Owner-approved Phase 2 causal engine завершена: bounded loader и deterministic short/medium/long real-data evidence прошли 15 focused tests; release/restore contract прошёл ещё 10 tests. Frozen roster и параметры не менялись, `BTWUSDT` остаётся missing/ineligible, holdout отсутствует. **PASS / DONE означает только причинность и воспроизводимость инженерного слоя, не торговый edge.** Parameter search, portfolio execution, PnL/backtest и holdout запрещены до отдельной frozen Phase 3 specification и нового owner approval; итоговый отчёт — `reports/ALTCOIN_MULTITF_005_PHASE2.md`, gated handoff — `docs/ALTCOIN_MULTITF_005_PHASE3_NEXT_CHAT.md`.

**Независимое altcoin-исследование:** строгий protocol `ALT-XSMOM-001-A` остаётся **STOP** из-за отсутствия полного historical lifecycle registry. Разрешённый exploratory amendment `ALT-XSMOM-001-B` на frozen basket из 10 контрактов завершил pre-HOLDOUT TRAIN/VALIDATION с **FAIL / STOP**. TRAIN-only selection выбрал `30d momentum / 24h rebalance`; на единственной VALIDATION при 0,12% net Sharpe равен `−0,817`, compounded return `−35,90%`, max drawdown `−46,78%`, bootstrap CI95 `[−2,449; +0,632]`. Результат при 0,20% также отрицателен (`−60,99%`). HOLDOUT с `2026-01-01` не открывался и остаётся закрытым. Это **exploratory fixed-basket evidence with survivorship/selection bias**, не universe-level edge. См. [`reports/ALTCOIN_PHASE_B_TRAIN_VALIDATION.md`](../reports/ALTCOIN_PHASE_B_TRAIN_VALIDATION.md).

## Legacy ETH status

ETHUSDT 1h кандидат повторно проверен walk-forward только на TRAIN+VALIDATION. Объединённый OOS-результат положителен в обеих схемах:

- anchored: 42 сделки, `+0,221R` expectancy, `+9,279R`, PF `1,602`, 3/4 положительных окон;
- rolling: 75 сделок, `+0,086R` expectancy, `+6,476R`, PF `1,195`, 2/4 положительных окон.

Положительный результат зафиксирован, но не считается подтверждённым edge: rolling-результат исчезает после удаления лучших пяти сделок, 2022 год отрицателен, а Phase 4 не подтвердила простой 24h continuation-механизм (`−0,018%` gross через 24 часа и `−0,547` п.п. относительно главного контроля). Закрытый TEST не открывался.

Актуальные материалы:

- `reports/PHASE1_AUDIT.md`;
- `reports/PHASE2_WALK_FORWARD.md` — оригинальная Phase 2;
- `reports/PHASE2_WALK_FORWARD_REPEAT.md` — дополнительный повтор Phase 2;
- `reports/PHASE3_PARAMETER_STABILITY.md` — оригинальная Phase 3;
- `reports/PHASE3_ROBUSTNESS.md` — дополнительная повторная robustness-проверка;
- `reports/PHASE4_ECONOMIC_MECHANISM.md`;
- `reports/TIMEFRAME_ROBUSTNESS_M15_M30.md`;
- `reports/REGIME_CONCENTRATION.md` — отдельная pre-TEST regime/concentration-диагностика, не Phase 2–4;
- `docs/PHASE5_PROTOCOL.md` и `reports/PHASE5_FALSIFICATION.md`;
- машинные артефакты в `reports/phase2/`, `reports/phase2-repeat/`, `reports/phase3/`, `reports/phase4/`, `reports/timeframe-robustness/`, `reports/regime-concentration/` и `reports/phase5/`.

`reports/BEST_RESULT_SO_FAR.md` и исходный diagnostic JSON сохранены только как исторические артефакты до исправления утечки VALIDATION-калибровки.

## Важное уточнение по комиссиям BingX

Если ставка taker составляет 0,05% **за исполнение**, комиссия списывается отдельно при открытии и при закрытии позиции:

- вход: 0,05% от номинала;
- выход: 0,05% от номинала;
- полный круг: примерно 0,10% от номинала без учёта funding и slippage.

То, что позиция экономически является одной сделкой, не означает одно биржевое исполнение: вход и выход — два отдельных ордера. Если указанная в аккаунте ставка 0,05% уже обозначает комиссию **за полный круг**, а не за сторону, базовый тест следует проводить именно с 0,05%. Это необходимо проверить по фактической выписке BingX, а не по общему тарифу.

Небольшой депозит сам по себе не снижает процентную комиссию: она считается от номинала позиции. Но небольшой ордер на ликвидных BTC/ETH действительно обычно уменьшает market impact. Поэтому slippage не следует завышать, но полностью обнулять его до проверки реальных исполнений тоже не стоит.

Рабочая сетка расходов для следующего этапа:

| Сценарий | Полные расходы | Назначение |
|---|---:|---|
| Фактический минимум | 0,05% | Только если выписка подтверждает 0,05% за полный круг |
| Taker/taker без slippage | 0,10% | Если 0,05% списывается на каждой стороне |
| Реалистичный | 0,11–0,12% | Комиссии плюс небольшой slippage |
| Стресс | 0,16% | Проверка запаса прочности, не основной сценарий |

Funding необходимо учитывать отдельно по фактическим timestamps удержания позиции.

# Этап 1. Не «задушить» текущего ETH-кандидата

Цель этапа — не требовать от кандидата идеальной прибыли в каждом срезе, а определить, является ли validation-результат повторяемым или случайным следствием перебора.

## 1.1. Зафиксировать спецификацию

До открытия закрытого test сохранить без изменений:

- формулу сигнала;
- направление;
- таймфрейм;
- universe;
- параметры VWAP, режима BTC и волатильности;
- стоп, тейк и максимальное удержание;
- правила исполнения;
- комиссии, slippage и funding;
- правила размера позиции;
- критерии оценки.

После просмотра test параметры этой версии не менять. Любое изменение считается новой гипотезой.

## 1.2. Аудит backtest

Проверить:

- отсутствие look-ahead bias;
- сигнал только по закрытой часовой свече;
- вход не раньше следующего доступного исполнения;
- корректное исполнение gap через стоп;
- консервативны�� порядок, если внутри одной свечи затронуты стоп и тейк;
- отсутствие пересечения позиций и повторного использования одного капитала;
- корректные комиссии на обеих сторонах;
- funding по времени удержания;
- отсутствие пропусков и дублей данных.

## 1.3. Полный журнал сделок

Для каждой сделки сохранить:

- timestamp сигнала, входа и выхода;
- цену входа и выхода;
- стоп и тейк;
- номинал позиции;
- gross PnL;
- комиссию входа и выхода;
- funding;
- slippage;
- net PnL;
- результат �� R;
- MAE и MFE;
- длительность;
- причину вых������������������������да;
- рыночный режим.

Результат сделки считать как:

$$R_i = \frac{NetPnL_i}{InitialRisk_i}$$

## 1.4. Мягкий диагностический отбор

Не при��енять требование «каждый период обязан быть прибыльным». Трендовая или режимная система закономерно может иметь убыточные окна.

Кандидатов ранжировать по совокупности:

- expectancy в R;
- нижней границе bootstrap-интервала;
- Profit Factor;
- максимальной просадке в R;
- количеству сделок;
- стабильности соседних параметров;
- концентрации прибыли;
- результату при разных расходах.

Сохранять top-20 даже при непрохождении формального gate.

# Этап 2. Walk-forward те����ущего кандидата

## 2.1. ��хема проверки

Базова�� схема:

- train: 12 месяцев;
- validation: следующие 3 месяца;
- шаг: 3 месяца;
- повторение до конца доступной истории.

Для редкого сигнала доп��лнительно проверить вариант 18/6 месяцев, чтобы избежать выводов по слишком малому числу сделок.

На каждом окне параметры выбираются только по train. Все последовательные validation-периоды объединяются в одну out-of-sample кривую.

## 2.2. Что измерять

- общий OOS expectancy в R;
- медианный expectancy окна;
- долю прибыльных окон;
- total R;
- максимальную просадку;
- число сделок по окнам;
- результат по годам;
- вклад лучших 1, 3 и 5 сделок;
- long/short и BTC/ETH отдельно, если применимо;
- чувствительность к расходам 0,05%, 0,10%, 0,12% и 0,16%.

Убыточное отдельное окно не является автоматической причиной отказа. Критично, чтобы общая OOS-прибыль не создавалась одним коротким периодом.

# Этап 3. Устойчивость параметров

Проверить не одну оптимальную точку, а соседнюю область:

- VWAP: 12, 24, 48 и 72 часа;
- сто��: 1,2 / 1,5 / 1,8 / 2,0 ATR;
- тейк: 1,5 / 2,0 / 2,5 / 3,0 ATR;
- удержание: 12 / 24 / 36 / 48 часов;
- несколько соседних порогов отклонения и волатильности;
- несколько разумных определений режима BTC.

Признак edge — положительный кластер параметров. Прибыль �� одной узкой комбинации является признаком переобучения.

Выбирать следует центральную или медианную конфигурацию устойчивого кластера, а не абсолютный исторический максимум.

# Этап 4. Проверить экономический механизм

Текущий сигнал предполагает продолжение силы ETH в специфическом состоянии рынка. Необходимо выяснить, что именно его создаёт:

1. относительная сила ETH к BTC;
2. short squeeze;
3. запаздывание ETH относительно BTC;
4. восстановление после панического движения;
5. артефакт отдельного исторического периода.

Добавить признаки:

- ETH/BTC momentum;
- разницу доходностей ETH и BTC;
- импульс BTC за 1, 4, 12 и 24 часа;
- funding ETH и BTC;
- изменение open interest;
- объём и его z-score;
- расстояние до VWAP в ATR;
- basis;
- ликвидации или их proxy.

Новый признак добавляется только как отдельная заранее описанная гипотеза, а не для косметического улучшения уже просмотренного результата.

# Этап 5. Параллельные семейства гипотез

Проверять экономически разные идеи отдельными экспериментами.

## 5.1. ETH/BTC relative strength

Ближайшее продолжение текущего результата:

- относительный momentum ETH/BTC;
- расхождение доходностей ETH и BTC;
- разница funding;
- разница изменения OI;
- относительный объём.

## 5.2. Price + open interest regimes

Отдельно проверить четыре режима:

| Цена | OI | Возможный механизм |
|---|---|---|
| Растёт | Растёт | Набор новых long |
| Растёт | Падает | Закрытие short |
| Падает | Растёт | Набор новых short |
| Падает | Падает | Капитуляция long |

Для каждого режима отдельно тестировать continuation и reversal.

## 5.3. Funding + OI + price

Funding не использовать изолированно. Проверять сочетания:

- отрицательный funding + рост цены + рост OI;
- положительный funding + падение цены + рост OI;
- экстремальный funding без подтверждения цены;
- резкое изменение funding;
- расхождение funding между BTC и ETH.

## 5.4. Volatility expansion

Искать выход из сжатия:

- низкий ATR percentile;
- узкий диапазон;
- рост объёма;
- пробой локального диапазона;
- подтверждение или расхождение с BTC.

Long и short проверять отдельно.

## 5.5. Liquidation continuation/reversal

Проверить:

- продолжение после каскада ликвидаций;
- возврат к VWAP после экстремального ка��када;
- зависимость от funding, OI и времени суток.

При отсутствии прямых данных использовать заранее определённый proxy: широкий диа��азон свечи, всплеск объёма и резкое падение OI.

## 5.6. Cross-sectional momentum

После проверки BTC/ETH расширить universe только на ликвидные perpetual-контрак��ы:

- фильтр ликвидности;
- исключение новых инструментов;
- ранжирование относительной силы;
- beta-neutral вариант;
- ребалансировка 4–24 часа;
- отдельный учёт комиссий и funding.

# Этап 6. Статистика и защита от перебора

Для каждого семейства фиксировать:

- идентификатор эксперимента;
- эк��н����ми��ес��ую гипотезу;
- д��ст��пн��е на ��омент сигнала данные;
- пространство параметров;
- число проверенных ва��иант��в;
- train/validation/test границы;
- кр��тери�� принятия решения;
- все отрицательные результаты.

Использовать:

- bootstrap по сделкам и временным блокам;
- поправку на multiple testing;
- parameter-cluster analysis;
- sensitivity analysis;
- сравнение с простым baseline;
- deflated Sharpe или аналогичную поправку при большом переборе.

Не выбирать стратегию только по максимальному Sharpe или PF.

# Этап 7. Метрики решения

Главная метрика:

$$Expectancy_R = WinRate \times AvgWin_R - LossRate \times AvgLoss_R$$

Дополнительно:

- median R;
- total R;
- Profit Factor;
- max drawdown в R;
- Sharpe, Sortino и Calmar;
- recovery factor;
- средняя длительность;
- сделок в месяц;
- turnover;
- funding drag;
- результат по режимам;
- доля прибыли лучших сделок.

Кон��ент��ация прибыли:

$$Concentration_5 = \frac{PnL\ лучших\ 5\ сдел��к}{TotalPnL}$$

Если несколько сделок создают почти весь результат, уверенность в edge снижается.

# Этап 8. Закрытый test

Открывать test один раз т��лько после:

- аудита движка;
- walk-forward;
- ��нали��а соседних параметров;
- фиксации расходов;
- заморозки спецификации.

Результат test не использовать для подстройки той же версии. При изменении правил создаётся новая версия гипотезы и используется новый будущий holdout/forward период.

# Этап 9. Критерии перехода в paper trading

Ориентиры, а не жёсткая машина допуска:

- положительный объединённый OOS expectancy;
- разумное количество не��ависимых сделок либо достаточная длительность для редкого сигнала;
- PF около 1,2 или выше после фактических расходов;
- положительный результат в большинстве walk-forward окон;
- отсутствие зависимости от одного периода или нескольких сделок;
- положительная область соседних параметров;
- понятный экономический механизм;
- закрытый test не противоречит гипотезе.

Не требовать прибыльности каждого окна и не использовать стрессовую комиссию как единственную основную модель.

# Этап 10. Paper trading и реальное исполнение BingX

Начать с 50–100 сигналов либо заранее определённого минимального периода для редкой стратегии.

Для каждого сигнала сравнивать:

- теоретический backtest fill;
- доступную рыночную цену;
- фактический BingX fill;
- комиссию по выписке;
- funding;
- slippage;
- итоговую разницу в R.

На этом этапе окончательно установить реальный round-trip cost для конкретного аккаунта и размера позиции.

# Этап 11. Риск после подтверждения

Если стратегия дойдёт до реальных денег:

- стартовый риск 0,25–0,5% капитала на сделку;
- без мартингейла и усреднения убытка;
- лимит коррелированной экспозиции;
- дневной и недельный stop-loss в R;
- остановка при превышении ожидаемой просадки;
- увеличение размера только после подтверждения live-статистикой.

Размер позиции:

$$PositionSize = \frac{Capital \times RiskFraction}{StopDistance}$$

# Выполненные фазы

- Phase 1: аудит движка, причинности, TRAIN-only calibration и журналов сделок.
- Оригинальная Phase 2: четыре anchored/rolling walk-forward-схемы дали положительный объединённый OOS; дополнительный повтор Phase 2 также положителен, но rolling без top-5 равен `−0,044R`; TEST закрыт.
- Оригинальная Phase 3: завершена карта 256 VALIDATION-конфигураций с широким положительным кластером. Отдельная повторная robustness-проверка по расходам, окнам, концентрации и однофакторным соседям завершена; её strict pass не пройден.
- Phase 4: анализ экономического механизма; простой специфический 24h continuation не подтверждён.
- Дополнительный frozen перенос на M30/M15: оба TF положительны при 0,10% до trimming, но оба отрицательны без top-5; M15 отрицателен при 0,16%. Строгий критерий поддержки не пройден, TEST закрыт.
- Отдельная regime/concentration-диагностика на полном TRAIN+VALIDATION 2021–2024: 1h `+16,387R` и `+9,808R` без top-5; M30 `+7,926R` и `+1,348R` без top-5; M15 `+0,654R` и `−5,910R` без top-5. Режимы и их thresholds каузальны; leave-one-year/regime-out сохранены отдельно. Это описательный pre-TEST срез, не новая OOS-оценка и не замена результатам Phase 2–4.
- Phase 5: frozen 1h получил PASS 7/7 по заранее зафиксированному protocol: без top-5 `+9,808R`, без 2024 `+7,294R`, без лучшего 90-day кластера `+8,330R`, при 0,16% `+12,210R`, rolling 12m positive share 78,4%, все обязательные leave-one-regime-out положительны, combined stress `+4,792R`. Отдельный one-bar-delay stress отрицателен (`−2,358R`), а longest no-new-high около 970 дней. TEST не открыт.
- Governance gate завершён: immutable memo и SHA-256 manifest фиксируют research commit `81f5ea590edbc04fadce762452801c1d365470d0`, 192 исходных pre-TEST ZIP, research artifacts, единственную TEST-ком��нду и CI95 verdict. Frozen strategy/cost/execution не менялись.
- Единственный TEST 2025 завершён с **FAIL**: 32 сделки, expectancy `−0,160R`, total `−5,135R`, CI95 `[−0,495R; +0,186R]`, max drawdown `−5,640R`. Старый candidate отклонён; повторный запуск и retuning по TEST запрещены.

# Ближайшая последовательность работ

1. Старый ETH candidate остаётся окончательным FAIL; никогда не открывать TEST 2025 повторно.
2. Frozen exploratory `ALT-XSMOM-001-B` завершён с FAIL; не выбирать другую конфигурацию из просмотренной grid и не менять basket.
3. HOLDOUT с `2026-01-01` не открывать и не анализировать.
4. Не переходить к paper/live trading для этой версии.
5. Любая нов��я гипотеза возм��жна только пос��е отдельного owner decision, с новым protocol ID и новым будущим sealed holdout.

## Зафиксированный пофазный план после FAIL

1. **Фаза 0 — закрытие `ALT-XSMOM-001-B` (DONE):** окончательный FAIL / STOP; retuning, paper/live и повторный выбор grid запрещены.
2. **Фаза 1 — read-only post-mortem (DONE):** существующие ledgers разложены по costs, turnover, legs, symbols, funding, concentration и календарным срезам без новых backtests.
3. **Gate 1 — owner decision (DONE):** владелец разрешил только документационную Фазу 2.
4. **Фаза 2 — новый protocol (DONE):** до реализации frozen `ALT-LOMOM-002-A` с единственным low-turnover long-only кандидатом, mechanical PASS/FAIL и новым prospective calendar.
5. **Фаза 3 — реализация и TRAIN (DONE):** один preregistered вариант реализован и р��ссчитан только на timestamps `< 2026-01-01`; TRAIN diagnostic PASS, ledger reconciliation PASS.
6. **Фаза 4 — prospective VALIDATION (NOT STARTED):** `[2026-09-01, 2027-09-01)`, один заранее определённый запуск с механическим gate без retuning; отдельное разрешение обязательно.
7. **Фаза 5 — paper trading (CONDITIONAL):** только после уверенного PASS и отдельного разрешения; live остаётся отдельным решением.

## Текущее решение

Старые altcoin маршруты остаются остановленными. Новая adaptive гипотеза зафиксирована в [`docs/ALTCOIN_LONG_ONLY_PROTOCOL.md`](./ALTCOIN_LONG_ONLY_PROTOCOL.md): fixed basket, `30d` momentum, long-only top 4, weekly rebalance, portfolio-level 20% volatility target, один candidate без grid. Все данные до 2026 года contaminated и считаются DEVELOPMENT/TRAIN; prospective VALIDATION начинается `2026-09-01`, новый sealed HOLDOUT — `2027-09-01`. **Фаза 3 DONE; TRAIN diagnostic PASS; текущая точка — STOP перед Фазой 4.** На TRAIN: Sharpe `1,1508`, return `+270,37%` при 0,12%, stress `+254,18%`, max drawdown `−28,00%`, bootstrap lower `+0,2308`, 0 нарушений. Это fixed-basket evidence с survivorship/selection bias. Prospective VALIDATION и любые следующие действия не разрешены без нового owner decision.

## Новый независимый multi-timeframe research plan

Владелец отдельно одобрил только план нового исследовательского контура, описанный в [`docs/ALTCOIN_RESEARCH_ENGINE_PROTOCOL.md`](./ALTCOIN_RESEARCH_ENGINE_PROTOCOL.md). Он не изменяет `ALT-LOMOM-002-A`: текущая версия остаётся baseline и не подвергается retuning. Новый контур раздельно сравнит portfolio signals и trade signals с TP/SL на Binance USD-M perpetuals, primary lifecycle universe и TF `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `1d`.

Поиск будет контролируемо широким, с раздельными leaderboard, nested walk-forward и multiple-testing correction. Весь frozen диапазон 2026 года должен оставаться untouched и открываться один раз только после freeze по одному победителю каждого семейства.

### Новый engine: пофазный статус

0. **Phase 0 — protocol freeze (DONE):** создан [`docs/ALTCOIN_MULTITF_FROZEN_PROTOCOL.md`](./ALTCOIN_MULTITF_FROZEN_PROTOCOL.md). Зафиксированы development `[2019-09-08, 2026-01-01)`, sealed holdout `[2026-01-01, 2026-08-01)`, пять annual outer folds с expanding annual inner folds, purge `97d`, embargo `7d`, point-in-time lifecycle universe, moderate liquidity filter, конечный search manifest обоих семейств, execution/cost/risk model, score, SPA `5%`, DSR `95%`, robustness/concentration и mechanical PASS/FAIL.
1. **Owner gate Phase 1 (DONE):** владелец разрешил разделить Phase 1 и выполнить первую часть.
2. **Owner amendment A1 (DONE):** владелец разрешил current-roster universe и принял survivorship/coverage bias. Полный historical registry delisted/failed contracts больше не gate; roster snapshot должен быть заморожен до acquisition и не меняться по результатам coverage.
3. **Phase 1A — acquisition/sealing (DONE):** официальный current roster заморожен до data acquisition: `527` symbols, raw metadata SHA-256 `3c0d748c…`. Binance Vision inventory: `30,321` raw files / `4,938,089,720` bytes; development `23,167`, physically isolated holdout `7,154`. Manifest SHA-256 `5a2cba83…`; duplicate/boundary/overlap/filesystem hash checks и 7 acquisition/sealing tests PASS. Official archive limitation: development начинается `2020-01-01`, 47 current symbols не имеют development archives, `DOSUSDT` не имеет holdout archive; frozen roster не изменён.
4. **Phase 1B — normalization/eligibility audit (BLOCKED):** только после фактического PASS 1A и отдельного owner approval; development-only quality audit, causal eligibility внутри frozen roster и агрегация `15m/30m/1h/2h/4h/1d` из raw `5m`, manifests/hashes. Prompt Phase 1A continuation: [`docs/ALTCOIN_MULTITF_PHASE1B_NEXT_CHAT.md`](./ALTCOIN_MULTITF_PHASE1B_NEXT_CHAT.md).
5. **Phase 2 — causal engine (NOT APPROVED):** отдельный будущий gate; implementation и tests без parameter selection.
6. **Phase 3 — nested walk-forward sweep (NOT APPROVED):** два полных leaderboard без holdout.
7. **Phase 4 — frozen robustness (NOT APPROVED):** только заранее заданные stresses/gates, без расширения grid.
8. **Phase 5 — shortlist freeze (NOT APPROVED):** ровно один PASS winner каждого семейства; если family FAIL, winner отсутствует.
9. **Phase 6 — one-time holdout (NOT APPROVED):** один совместный invocation двух immutable winners; только если оба family прошли и владелец отдельно разрешил откр��тие.
10. **Phase 7 — paper signals (NOT APPROVED):** только после holdout PASS и отдельного решения; live capital не разрешён.

**`ALT-MULTITF-003` закрыт как невосстан��вимый:** незакоммиченные raw payload/manifests Phase 1A утрачены с прежним sandbox; исторические факты строк 424–425 остаются только отчётом того запуска.

### Compact replacement `ALT-MULTITF-004`

1. **Protocol/universe freeze (DONE):** новый ID; 40 top-current-liquidity USDT perpetual altcoins по frozen official `ticker/24hr`, BTC/ETH исключены; survivorship/current-selection bias принят явно.
2. **Development acquisition (DONE):** `[2020-01-01, 2026-01-01)`, `3 291` raw monthly files / `568 466 246` bytes; только 5m+funding; `3 291/3 291` SHA-256 PASS; `BTWUSDT` оставлен в roster без history.
3. **Normalization/eligibility (DONE):** `14 276 432` 5m, `168 371` funding; `15m/30m/1h/2h/4h/1d` только из закрытых 5m; 18 gaps, 0 duplicates, 0 invalid; causal eligibility около 90,06% intraday decisions.
4. **Phase 2 causal engine (DONE):** owner-approved implementation фиксирует TF-group parameters, causal returns/momentum/volatility/trend/funding alignment, eligibility-before-ranking, deterministic ranking и schema-only portfolio handoff. Focused leakage tests PASS. Parameter search, construction execution, PnL и backtest не выполнялись.
5. **Dataset portability (DONE):** frozen 40-symbol Binance archive inventory восстановлен без нового roster selection и закреплён как SHA-256 verified private Blob bundle, доступный подключённым чатам через `BLOB_READ_WRITE_TOKEN`; committed restore tool fail-closed проверяет bundle до extraction.
6. **Phase 3 frozen strategy evaluation (INCOMPLETE / NO WINNER):** frozen manifest содержит 58 140 configs. Family A рассчитана полностью (`3 060/3 060`); лучший daily-proxy кандидат дал `+79,24%` cumulative net, `10,20%` annualized, Sharpe `1,465`, max drawdown `−5,68%`, но это не финальный winner. Family B (`0/55 080`), SPA/DSR, mandatory robustness и TF-native replay не завершены. Holdout не читался.
7. **Phase 4 completion (NEXT / OWNER-APPROVED PROMPT PREPARED):** нативный multi-TF replay, полный Family B, повтор затронутой Family A, SPA/DSR и frozen robustness gates только на DEVELOPMENT. Готовый handoff: [`docs/ALTCOIN_MULTITF_005_PHASE4_NEXT_CHAT.md`](./ALTCOIN_MULTITF_005_PHASE4_NEXT_CHAT.md).
8. **Shortlist freeze (CONDITIONAL):** максимум один PASS winner каждого семейства; при непрохождении gates — NO WINNER.
9. **One-time holdout (NOT APPROVED):** только отдельным следующим решением после полного Phase 4 PASS; до этого holdout остаётся sealed.
10. **Paper/live (NOT APPROVED):** только после holdout PASS и отдельных решений.

Protocol: [`docs/ALTCOIN_MULTITF_COMPACT_PROTOCOL.md`](./ALTCOIN_MULTITF_COMPACT_PROTOCOL.md). Phase 3 spec: [`docs/ALTCOIN_MULTITF_005_PHASE3_SPEC.md`](./ALTCOIN_MULTITF_005_PHASE3_SPEC.md). Profitability report: [`reports/ALTCOIN_MULTITF_005_PHASE3_PROFITABILITY.md`](../reports/ALTCOIN_MULTITF_005_PHASE3_PROFITABILITY.md). Наглядный TF-срез: [`reports/ALTCOIN_MULTITF_005_ASSET_TF_EXAMPLES.md`](../reports/ALTCOIN_MULTITF_005_ASSET_TF_EXAMPLES.md). **Текущая точка — PHASE 3 INCOMPLETE / NO WINNER; следующий этап — Phase 4 completion без holdout.**
