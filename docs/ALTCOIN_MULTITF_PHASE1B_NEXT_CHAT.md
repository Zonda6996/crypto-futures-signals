# Prompt для следующего чата — ALT-MULTITF-003 Phase 1A continuation

Продолжи работу в репозитории `Zonda6996/crypto-futures-signals`, ветка `v0/altcoin-momentum-analysis-25e7e60d`.

ЦЕЛЬ: выполнить только Phase 1A проекта `ALT-MULTITF-003` — acquisition и физическое sealing raw data. Не переходить к Phase 1B, signal research или backtest.

Сначала проверь, что HEAD содержит owner amendment A1, затем полностью прочитай:

- `docs/HANDOFF.md`
- `docs/roadmap.md`
- `docs/ALTCOIN_MULTITF_FROZEN_PROTOCOL.md`
- `reports/ALTCOIN_MULTITF_PHASE1A_ACQUISITION.md`
- `docs/ALTCOIN_MULTITF_PHASE1B_NEXT_CHAT.md`
- `research/altcoin_multitf_phase1a.py`
- `research/altcoin_phase_a_audit.py`
- `research/altcoin_basket_data.py`
- `research/data.py`
- `tests/test_altcoin_multitf_phase1a.py`
- `.gitignore`

## Зафиксированный owner decision

- Владелец явно разрешил использовать **current Binance USD-M linear USDT perpetual roster** и принял survivorship/coverage bias.
- Полный historical registry delisted/expired/failed contracts больше не требуется и не должен блокировать acquisition.
- Не добавляй delisted symbols вручную и не меняй frozen roster после просмотра coverage.
- Результаты будущего исследования будут относиться только к активам frozen current roster; это ограничение должно остаться в отчётах.
- Raw `5m` скачивается сейчас; `15m`, `30m`, `1h`, `2h`, `4h`, `1d` будут детерминированно агрегированы из `5m` только в Phase 1B.

## Текущий статус

- Phase 0 frozen; owner amendment A1 внесён до market-data acquisition и до любых расчётов.
- Raw market-data files: `0`.
- Holdout payload reads: `0`; sealed payload ещё не создан.
- Signals, ranking, PnL, backtest и grid search: `0`.
- Fail-closed acquisition/sealing infrastructure существует в `research/altcoin_multitf_phase1a.py`; 14 data/sealing tests проходили.
- `ALT-LOMOM-002-A` — неизменяемый отдельный baseline.

## Что сделать в Phase 1A

1. Получить current roster только из официального Binance source (`exchangeInfo` или официальный эквивалент). Если основной API geo-blocked, используй официальный доступный Binance endpoint/mirror или Binance Vision metadata. Не подменяй roster сторонним списком.
2. До скачивания market data сохранить immutable raw roster snapshot и canonical roster manifest со следующими полями, где они доступны: `symbol`, `pair`, `baseAsset`, `quoteAsset`, `marginAsset`, `contractType`, `status`, `onboardDate`, `deliveryDate`, filters, source URL, acquisition UTC timestamp, byte size и SHA-256.
3. Включить только current `PERPETUAL`, linear USD-M, quote/margin `USDT` contracts. Исключить delivery, COIN-M, USDC и synthetic/index instruments. Заморозить roster до проверки market-data coverage.
4. Идемпотентно скачать из официального Binance Vision/API для каждого frozen symbol:
   - raw `5m` klines;
   - funding rates;
   - metadata/contract filters, необходимые для будущей eligibility/execution проверки.
5. Соблюсти интервалы UTC строго как полуоткрытые:
   - development `[2019-09-08T00:00:00Z, 2026-01-01T00:00:00Z)`;
   - sealed holdout `[2026-01-01T00:00:00Z, 2026-08-01T00:00:00Z)`.
6. Физически разделить development и holdout в разных каталогах. Research/normalization code не должен иметь путь или API чтения sealed payload. После записи holdout разрешены только filename, size, bounded timestamp metadata и SHA-256; не просматривать, не агрегировать и не анализировать его содержимое.
7. Реализовать безопасное возобновление: temporary files, atomic rename, checksum verification, skip только при совпадающем hash, retry с backoff, fail-closed при partial/corrupt/conflicting file.
8. Создать manifest каждого raw-файла: relative path, byte size, SHA-256, source URL, symbol, datatype, timeframe, requested start/end, observed first/last timestamp, acquisition timestamp и status.
9. Проверить duplicate paths/content, development/holdout overlap, timestamps вне границ, missing expected archives и несоответствия manifest/filesystem. Не нормализовать и не импутировать данные.
10. Не коммитить heavy raw files; сохранить их под ignored `data/altcoin-multitf-003/`.
11. Запустить только unit/integrity tests acquisition/sealing. Не запускать весь research pipeline.
12. Обновить `reports/ALTCOIN_MULTITF_PHASE1A_ACQUISITION.md`, `docs/HANDOFF.md`, `docs/roadmap.md` и этот handoff фактическими counts/ranges/gaps/hashes.
13. Проверить `git diff`, commit и push в ту же ветку. Остановиться после Phase 1A.

## Критерий PASS Phase 1A

- official current roster snapshot сохранён, провенанс и SHA-256 воспроизводимы;
- roster заморожен до coverage inspection;
- raw development `5m`/funding/metadata получены для всех roster symbols либо каждый официальный source gap явно перечислен и механически классифицирован;
- holdout физически изолирован и не читался исследовательским кодом;
- manifest/hash inventory полны и согласованы с filesystem;
- duplicate/overlap/boundary/sealing checks проходят;
- отчёт содержит точные числа контрактов и файлов, диапазоны, bytes, hashes, gaps и survivorship limitation.

Если официальный current roster вообще нельзя получить, остановись с честным `BLOCKED`; отсутствие historical delisted registry блокером больше не является.

## Жёсткие запреты

- не расширять roster по результатам качества/доходности;
- не читать и не анализировать sealed holdout payload;
- не выполнять Phase 1B normalization, eligibility или старшие TF;
- не запускать signals, ranking, portfolio construction, PnL, backtest, sweep, SPA/DSR или robustness;
- не выбирать TF, asset, lookback, TP/SL/trailing;
- не менять search space, calendar или PASS/FAIL criteria;
- не менять `ALT-LOMOM-002-A`;
- не запускать paper/live trading;
- не коммитить raw market data.

В конце простыми словами сообщи:

- источник и acquisition timestamp frozen roster;
- сколько контрактов и raw-файлов получено;
- какие development/holdout диапазоны покрыты;
- где физически находится sealed holdout;
- как подтверждены его границы и неизменность;
- какие gaps/blockers остались;
- PASS/FAIL Phase 1A и готова ли Phase 1B;
- commit hash и push status.
