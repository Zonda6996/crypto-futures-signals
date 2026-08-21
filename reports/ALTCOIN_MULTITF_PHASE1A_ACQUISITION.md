# ALT-MULTITF-003 — Phase 1A acquisition gate

Статус: **STOP / BLOCKED BEFORE DOWNLOAD**

Дата: 22 августа 2026 года

## Scope

Phase 1 разделена без изменения frozen research protocol:

- **Phase 1A:** доказать наличие полного point-in-time lifecycle registry, затем получить raw development/holdout snapshots, физически изолировать holdout и записать SHA-256 inventory.
- **Phase 1B:** только после PASS Phase 1A нормализовать development payload, проверить качество/eligibility, агрегировать TF и выпустить итоговый data audit.

Обе части запрещают signals, ranking, PnL, backtest, parameter selection и чтение holdout payload исследовательским процессом.

## Pre-download gate

До сетевой загрузки проверена доступность обязательного первичного ключа acquisition: полного датированного реестра всех Binance USD-M USDT perpetual contracts, включая delisted/failed contracts, с authoritative onboard/open и delist/close timestamps.

В репозитории такого реестра нет. Имеющиеся Binance Vision loaders работают только после получения symbol list и не могут доказать, что исторические delisted symbols не были пропущены. Текущий `exchangeInfo` является roster на дату запроса после начала sealed holdout и не восстанавливает полный исторический состав. Использование его как seed внесло бы survivorship bias и post-holdout leakage.

Это тот же класс блокера, который ранее был честно обнаружен в `ALT-XSMOM-001-A`; новый protocol явно запрещает обход блокера современной fixed basket.

## Выполненные и невыполненные действия

Выполнено:

- зафиксировано безопасное разделение Phase 1A/1B;
- проверены существующие data loaders и capability audit;
- подтверждено отсутствие подходящего lifecycle registry в versioned inputs;
- сохранена закрытость holdout `[2026-01-01T00:00:00Z, 2026-08-01T00:00:00Z)`.

Не выполнялось:

- market-data download: `0` запросов;
- чтение/парсинг holdout payload: `0` файлов;
- signal/PnL/backtest/grid search: `0` запусков;
- изменение `ALT-LOMOM-002-A`: отсутствует.

Массовая загрузка symbol-addressed свечей до разрешения registry gate намеренно не начата: она не исправила бы неизвестный missing-symbol set и создала бы дорогой, но непригодный dataset.

## Verdict

**Phase 1A = STOP.** Acquisition и sealing не завершены. Phase 1B пока запрещена, поскольку ей нечего безопасно нормализовать и lifecycle eligibility нельзя сертифицировать.

## Что требуется для снятия STOP

Владелец должен предоставить или отдельно одобрить конкретный источник полного исторического lifecycle registry. Источник должен:

1. покрывать весь development `[2019-09-08, 2026-01-01)` и перечислять delisted/failed USD-M USDT perpetuals;
2. содержать authoritative onboard/open и delist/close timestamps с provenance;
3. быть snapshot/versioned так, чтобы его полноту можно было независимо проверить;
4. не подменяться current roster, современной basket или списком победивших активов.

После этого отдельный чат сначала повторяет Phase 1A gate. Только при PASS он загружает raw `5m`, funding и point-in-time contract filters, физически разделяет development/holdout и создаёт file inventory с hashes. Phase 1B начинается лишь после отдельного owner approval следующего gate.
