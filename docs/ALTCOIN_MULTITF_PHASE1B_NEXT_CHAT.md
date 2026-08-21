# Prompt для следующего чата — ALT-MULTITF-003 Phase 1 continuation

Продолжи работу в репозитории `Zonda6996/crypto-futures-signals`, ветка `v0/altcoin-momentum-analysis-25e7e60d`.

Сначала полностью прочитай:

- `docs/HANDOFF.md`
- `docs/roadmap.md`
- `docs/ALTCOIN_MULTITF_FROZEN_PROTOCOL.md`
- `reports/ALTCOIN_MULTITF_PHASE1A_ACQUISITION.md`
- `research/altcoin_phase_a_audit.py`
- `research/altcoin_basket_data.py`
- `tests/test_altcoin_phase_a_audit.py`

## Текущий статус

- Phase 0 protocol `ALT-MULTITF-003` frozen.
- Phase 1 разделена на Phase 1A acquisition/sealing и Phase 1B normalization/eligibility audit.
- Первая попытка Phase 1A остановлена до загрузки: в versioned inputs нет полного point-in-time Binance USD-M lifecycle registry с delisted/failed contracts.
- Network market-data requests: 0.
- Holdout payload reads: 0.
- Signal/PnL/backtest runs: 0.
- `ALT-LOMOM-002-A` неизменяем и не относится к этому исследованию.

Перед началом владелец должен приложить или явно назвать одобренный источник полного lifecycle registry. Если такого ввода нет, остановись и запроси его; current exchange roster, современная fixed basket и реконструкция только по известным symbols запрещены.

## Цель

Сначала завершить **Phase 1A**, и только после её PASS и отдельного owner approval выполнить **Phase 1B**. Не объединять gates молча.

### Phase 1A — acquisition и sealing

1. Проверить completeness/provenance lifecycle registry на `[2019-09-08, 2026-01-01)`; включить delisted/failed USD-M USDT perpetuals и onboard/delist timestamps.
2. При FAIL выпустить обновлённый STOP report и не скачивать symbol-addressed market data.
3. При PASS реализовать/запустить idempotent raw acquisition только для `5m` klines, funding и point-in-time contract filters.
4. Разделить интервалы строго по UTC:
   - development `[2019-09-08T00:00:00Z, 2026-01-01T00:00:00Z)`;
   - sealed holdout `[2026-01-01T00:00:00Z, 2026-08-01T00:00:00Z)`.
5. Holdout сохранять в отдельном sealed path. Research/normalization process не должен иметь путь или API чтения payload; допустимы только filenames, byte sizes, bounded timestamps и SHA-256.
6. Создать acquisition manifest: source URL/provenance, symbol, kind, interval, period, byte size, first/last timestamp, status и SHA-256. Raw payload не коммитить.
7. Запустить unit/integrity tests для boundary rejection, path isolation, retries, idempotency и deterministic hashes.
8. Обновить report/HANDOFF/roadmap, commit и push. Остановиться перед Phase 1B и запросить owner approval.

### Phase 1B — только после отдельного owner approval

1. Читать только development payload.
2. Проверить duplicates, conflicting duplicates, ordering, off-grid timestamps, incomplete final bars, gaps, OHLC/volume validity, funding completeness и lifecycle consistency.
3. Не импутировать bars, funding или lifecycle timestamps.
4. Построить canonical lifecycle registry и causal eligibility audit по frozen правилам: age `90d`, trailing `30d` 5m coverage `>=99%`, no gap `>30m`, median 30 full UTC-day quote volume `>=25m USD`.
5. Детерминированно агрегировать `15m/30m/1h/2h/4h/1d` только из закрытых clean `5m` bars; проверить UTC boundaries и expected counts.
6. Создать normalized development manifests/hashes и Phase 1 final PASS/FAIL report. Не создавать signal features или returns.
7. При любой неоднозначности — STOP и owner amendment, а не выбор после просмотра данных.

## Жёсткие запреты

- не читать и не анализировать holdout payload;
- не запускать signals, ranking, PnL, backtest, sweep, SPA/DSR или robustness;
- не выбирать TF, asset, lookback, TP/SL/trailing;
- не менять frozen protocol/search space;
- не менять и не смешивать `ALT-LOMOM-002-A`;
- не запускать paper/live;
- не коммитить raw market data;
- не переходить к Phase 2 engine implementation.

В конце простыми словами сообщи: что удалось получить, прошёл ли lifecycle gate, остался ли holdout закрытым, какие data-quality проблемы найдены, PASS/FAIL текущей части и какой единственный следующий шаг разрешён.
