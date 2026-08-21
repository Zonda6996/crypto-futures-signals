# ALT-MULTITF-003 — Phase 1A acquisition gate

Статус: **BLOCKED BEFORE DOWNLOAD (lifecycle registry не доказуем)**

Дата: 22 августа 2026 года

Ветка: `v0/altcoin-momentum-analysis-25e7e60d`

## Scope

Phase 1 разделена без изменения frozen research protocol:

- **Phase 1A:** доказать наличие полного point-in-time lifecycle registry, затем получить raw development/holdout snapshots, физически изолировать holdout и записать SHA-256 inventory.
- **Phase 1B:** только после PASS Phase 1A нормализовать development payload, проверить качество/eligibility, агрегировать старшие TF (`15m/30m/1h/2h/4h/1d` строятся из `5m`) и выпустить итоговый data audit.

Обе части запрещают signals, ranking, PnL, backtest, parameter selection и чтение holdout payload исследовательским процессом. По owner-решению в этом чате Phase 1A скачивает только raw `5m`; старшие TF не скачиваются и не агрегируются здесь.

## Что проверялось на pre-download gate

Первичный ключ acquisition — полный датированный реестр всех Binance USD-M USDT-margined perpetual contracts за development `[2019-09-08, 2026-01-01)`, включая delisted/expired/failed contracts, с authoritative onboard/open и delivery/delist timestamps и воспроизводимым provenance.

Проверены реально доступные официальные источники:

1. **Binance USD-M `GET /fapi/v1/exchangeInfo`.** Из sandbox возвращает `HTTP 451` (geo-block), но принципиально это current roster на момент запроса. Даже при доступе это snapshot *после* начала sealed holdout: он не перечисляет контракты, которые были delisted до запроса, и его использование как seed внесло бы survivorship bias и post-holdout leakage. Поля `onboardDate`/`deliveryDate`/`status` есть только для сегодня живущих или недавно закрытых символов.
2. **Binance Vision listing (`s3-ap-northeast-1.amazonaws.com/data.binance.vision`, `data/futures/um/monthly/klines/`).** Успешно получен: `KeyCount=986`, `IsTruncated=false`, `832` символа с суффиксом `USDT` (в списке присутствуют и не-USDT, и USDC, и мусорные/тестовые префиксы). SHA-256 XML-ответа `d24a13b22caa8e2251aab3abe76762a76d2e909f636bbf393d4dd9e842dcc38f`. Архив **symbol-addressed**: он перечисляет символы, у которых есть klines-каталог, но не публикует authoritative onboard/delist даты и не гарантирует, что удалённые/переименованные контракты остались в листинге. Наличие каталога не эквивалентно датированному lifecycle, а отсутствие — не доказывает, что символа не существовало.
3. **Официальные delisting-архивы.** Единого официального machine-readable файла всех delisted USD-M perpetuals Binance не публикует; delistings доступны только как хронологические announcements в support-центре. Их нельзя воспроизводимо и полностью распарсить в датированный registry в рамках этого чата, а «додумывать» отсутствующие даты запрещено protocol-ом.

## Вывод по gate

Полный воспроизводимый point-in-time lifecycle registry на весь development-диапазон **построить доказательно нельзя** только из машинно-доступных официальных источников: список Vision доказывает присутствие символов, но не их onboard/delist границы и не полноту (delisted/renamed могли выпасть); `exchangeInfo` — post-holdout current roster; единого delisting-архива нет.

Согласно frozen protocol и явному требованию задачи, при недоказуемой полноте registry запрещено скачивать biased universe. Поэтому market-data download не запускался.

## Выполненные и невыполненные действия

Выполнено:

- подтверждено, что HEAD ветки содержит commit `b2a576f` (Phase 1 split);
- перечитаны frozen protocol, existing Phase 1A report, оба handoff-документа и data-loaders;
- добавлена инфраструктура Phase 1A (`research/altcoin_multitf_phase1a.py`): fail-closed lifecycle gate, half-open boundary classifier `[2019-09-08, 2026-01-01)` / `[2026-01-01, 2026-08-01)`, atomic idempotent raw writer, sealed-path research-reader denial и manifest-валидатор с проверкой дубликатов/границ;
- добавлены тесты инфраструктуры (`tests/test_altcoin_multitf_phase1a.py`), запущены только data/sealing тесты — 14 passed;
- каталог `data/altcoin-multitf-003/` добавлен в `.gitignore`.

Не выполнялось:

- market-data download: `0` запросов (только listing-metadata и geo-blocked exchangeInfo probe);
- чтение/парсинг holdout payload: `0` файлов; holdout `[2026-01-01T00:00:00Z, 2026-08-01T00:00:00Z)` не открывался;
- signal/PnL/backtest/grid search/TF-или-asset selection: `0`;
- изменение `ALT-LOMOM-002-A`, frozen search space или PASS/FAIL criteria: отсутствует.

## Verdict

**Phase 1A = BLOCKED.** Lifecycle gate не пройден, поэтому acquisition и sealing не выполнялись, а Phase 1B остаётся запрещённой. Инфраструктура и тесты sealing готовы и активируются автоматически, как только появится доказуемый registry.

## Что требуется для снятия блокера (owner decision)

Безопасные варианты, требующие решения владельца:

1. **Предоставить versioned lifecycle registry.** Владелец прикладывает или явно называет snapshot/versioned источник, который: покрывает весь development `[2019-09-08, 2026-01-01)`; перечисляет delisted/expired/failed USD-M USDT perpetuals; содержит authoritative onboard/open и delivery/delist timestamps с provenance; независимо проверяем на полноту; не подменяется current roster или современной basket. После этого Phase 1A gate повторяется, и при PASS запускается raw `5m` + funding + point-in-time contract filters acquisition, физическое sealing и SHA-256 manifest.
2. **Разблокировать официальный Binance доступ.** Дать окружение без `HTTP 451`, где можно собрать исторические `exchangeInfo`/`contractInfo` snapshots и полный announcement-архив, а затем детерминированно построить registry из первичных официальных данных с сохранением raw metadata и hashes.
3. **Явно одобрить документированный biased-universe диагностический прогон.** Только при письменном owner-approval, с явной маркировкой survivorship bias, вне frozen primary evidence. По умолчанию запрещено и здесь не выполнялось.

Пока ни один из вариантов не предоставлен, единственный разрешённый следующий шаг — получить owner decision. Phase 1B до PASS 1A запрещена.
