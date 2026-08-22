# Immutable TEST-opening memo

Статус: **FROZEN; TEST SEALED; AWAITING A NEW EXPLICIT OWNER APPROVAL**  
Дата фиксации governance-слоя: 21 августа 2026 года.  
Граница TEST: `2025-01-01 00:00:00 UTC` (`1735689600000` ms), TEST-период — календарный 2025 год.

Этот memo не открывает TEST. Phase 5 — описательная полная pre-TEST falsification, а не новая OOS-оценка. Оригинальные Phase 2–3 и дополнительные проверки остаются разными экспериментами; их результаты нельзя объединять.

## 1. Frozen commit

Неизменяемая исследовательская база — commit:

`81f5ea590edbc04fadce762452801c1d365470d0`

Последующий governance commit может содержать только этот memo, hash manifest, защищённый одноразовый runner, integrity tests и обновления статуса документации. Он не меняет frozen candidate, calibration, costs или правила исполнения.

## 2. SHA-256 pre-TEST данных и артефактов

Машиночитаемый allowlist: [`docs/test-opening-hashes.json`](./test-opening-hashes.json). Алгоритм всех digest — `SHA-256`.

- 192 исходных Binance USD-M monthly ZIP: BTCUSDT/ETHUSDT, 1h klines и funding, строго `2021-01`…`2024-12`. Их URL-идентичность, rows и SHA-256 перечислены пофайлово.
- Research artifacts хешируются как байты, зафиксированные frozen commit.
- Governance artifacts хешируются как байты текущего memo/gate слоя.
- Ни один файл, строка или digest TEST с `2025-01-01` не входит в manifest. TEST не загружался и не анализировался при его создании.

Без полного совпадения manifest runner завершается до первого доступа к TEST.

## 3. Единственная команда TEST-прогона

После отдельного approval владельца допускается ровно эта одна команда без изменений:

```bash
python3 -m research.test_opening --frozen-sha 81f5ea590edbc04fadce762452801c1d365470d0 --approve "I AUTHORIZE THE ONE-TIME TEST OPENING FOR 81f5ea590edbc04fadce762452801c1d365470d0"
```

Другие entrypoints, ручные notebook-запуски, предварительный просмотр TEST и повтор команды запрещены.

## 4. Неизменяемая спецификация, costs и execution

- Universe: ETHUSDT USD-M perpetual; BTCUSDT используется только для каузальных признаков режима.
- Timeframe: 1h; direction: long.
- Signal: `vwap_distance_24 >= 0.011212442111818932`, BTC 24h regime `bear`, `rv_24 >= 0.031884225572892805`.
- Frozen candidate: feature `vwap_distance_24`, `threshold_q=0.75`, horizon/max hold `24` bars, stop `1.5 ATR(24)`, take `2.0 ATR(24)`, side `+1`, volatility `high`.
- Calibration не пересчитывается на TEST: threshold и rv median выше передаются как константы.
- Сигнал использует только закрытую свечу; entry — open следующей 1h-свечи (`execution_delay=1`).
- Одновременно разрешена одна позиция; следующий сигнал после уже занятого интервала пропускается.
- Stop/take проверяются по OHLC; при одновременном касании stop имеет приоритет. Time exit — close последней разрешённой свечи.
- Funding учитывается по фактическим timestamps удержания, backward/as-of, без будущих значений.
- Primary costs: taker `5 bps` на каждую сторону, half-spread `0`, дополнительный slippage `0`: ровно `0.10%` round trip плюс funding.
- Initial risk: `1.5 × ATR(24) / entry`; результат сделки `R_i = net_return / initial_risk_return`.
- Размер позиции не влияет на R и не оптимизируется.

## 5. Единственный primary metric

Единственный primary metric — арифметическое среднее `expectancy_R` всех frozen TEST-сделок:

$$Expectancy_R = \frac{1}{N}\sum_{i=1}^{N}R_i$$

Для неопределённости заранее фиксируется двусторонний percentile CI95: iid bootstrap сделок с возвращением, seed `6996`, `100000` resamples, квантили `0.025` и `0.975`. CI95 — диапазон правдоподобных значений среднего; gate требует, чтобы даже его нижняя граница была выше нуля.

## 6. Бинарный pass/fail-критерий

`PASS` тогда и только тогда, когда одновременно:

1. TEST содержит не менее 30 сделок;
2. нижняя граница заранее заданного CI95 для `expectancy_R` строго больше `0`.

Во всех остальных случаях — `FAIL`, включая 0–29 сделок, нулевую нижнюю границу, ошибку данных или невозможность завершить единственный прогон. Критерий не изменяется после открытия.

## 7. Secondary diagnostics без влияния на verdict

Сохраняются trade count, point expectancy, обе CI bounds, total R, hit rate, Profit Factor, max drawdown, средний holding period, temporal/year/regime breakdowns и журнал сделок, если они доступны в frozen runner. Они только описательны: ни одна secondary metric не может повысить `FAIL` до `PASS`, понизить `PASS` до `FAIL` или инициировать новый выбор параметров.

## 8. Запрет повторной настройки и повторного открытия

После первой попытки открыть TEST запрещены: изменение сигнала, calibration, параметров, costs, execution, primary metric, bootstrap, threshold решения; исключение сделок; выбор подпериода; повторный запуск; повторное открытие; использование TEST для новой версии той же гипотезы. Любая будущая гипотеза требует нового будущего holdout/forward-периода, не 2025 TEST.

Runner создаёт exclusive-create sentinel **до** первого TEST-запроса. Даже аварийная попытка считается израсходовавшей право открытия и не может быть повторена.

## 9. Результаты и audit trail

До доступа к TEST runner проверяет full SHA, точную approval phrase, memo/manifest/artifact/source hashes и отсутствие sentinel/result. Затем атомарно и с `O_EXCL` создаёт `reports/private/test-opening/OPENED_ONCE.json`. Финальный `result.json` сохраняет command, UTC timestamps, frozen и governance SHA, manifest digest, Python/platform, source quality, primary verdict и verdict-neutral diagnostics. Файлы не перезаписываются; journal и сырые результаты не публикуются выборочно.

## 10. Owner approval gate

Текущее утверждение плана разрешало только подготовить memo; оно **не разрешает TEST**. После проверки этого governance-слоя владелец должен новым отдельным сообщением прислать точную фразу:

`I AUTHORIZE THE ONE-TIME TEST OPENING FOR 81f5ea590edbc04fadce762452801c1d365470d0`

Exact phrase + SHA означает: текст должен совпасть посимвольно и содержать полный 40-символьный frozen commit, а та же фраза и SHA должны быть переданы runner. Это двойной предохранитель от случайного запуска. До нового сообщения TEST остаётся закрытым.
