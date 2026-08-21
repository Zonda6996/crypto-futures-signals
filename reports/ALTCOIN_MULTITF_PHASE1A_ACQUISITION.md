# ALT-MULTITF-003 — Phase 1A Acquisition and Sealing Report

Статус: **DONE**

Дата acquisition: `2026-08-21` UTC

## Frozen roster

- Source: `https://www.binance.com/fapi/v1/exchangeInfo` (официальный Binance metadata endpoint).
- Raw response: `1,077,582` bytes.
- Raw SHA-256: `3c0d748c6ac699a7ed79baa3c7abf9f131b09c3d234ba5e33cc94295bd206242`.
- Acquisition timestamp: `2026-08-21T22:26:20.042747Z`.
- Frozen selection: `527` текущих `TRADING`, `PERPETUAL`, quote/margin `USDT` contracts.
- Snapshot был физически записан и проверен до первого market-data download; resume повторно валидирует raw response и snapshot и не пересчитывает roster по coverage.

## Raw acquisition

Источник market data: официальный `https://data.binance.vision`.

Скачаны только raw `5m` klines, raw monthly funding-rate archives и полный raw `exchangeInfo`, содержащий contract metadata и filters. Отдельные `15m/30m/1h/2h/4h/1d` не скачивались. Normalization, eligibility, signals, ranking, portfolio, PnL, backtest и grid search не выполнялись.

### Inventory

| Partition | Datatype | Files |
|---|---:|---:|
| development | 5m klines | 11,603 |
| development | funding | 11,564 |
| sealed holdout | 5m klines | 3,577 |
| sealed holdout | funding | 3,577 |
| **Total** | | **30,321** |

- Total raw bytes: `4,938,089,720`.
- Development: `23,167` files, `3,789,400,776` bytes.
- Sealed holdout: `7,154` files, `1,148,688,944` bytes.
- Unique manifest paths: `30,321`; duplicates: `0`; missing files: `0`.
- Manifest SHA-256: `5a2cba833af721d60b09177150e0e8866ae3ed3e12c6ca6ceab5aef5d93d73e6`.

## Time boundaries

Frozen requested ranges:

- development `[2019-09-08T00:00:00Z, 2026-01-01T00:00:00Z)`;
- holdout `[2026-01-01T00:00:00Z, 2026-08-01T00:00:00Z)`.

Official Binance Vision USD-M archive availability begins at `2020-01-01T00:00:00Z`; acquired development coverage is `[2020-01-01T00:00:00Z, 2026-01-01T00:00:00Z)`. The missing initial requested segment is `[2019-09-08T00:00:00Z, 2020-01-01T00:00:00Z)`. No synthetic data or unofficial source was substituted.

Holdout archives cover `[2026-01-01T00:00:00Z, 2026-08-01T00:00:00Z)`. Boundary violations and development/holdout overlaps: `0`.

## Coverage limitations

- `480/527` current-roster symbols have development archives; `47` were onboarded after the development end or otherwise have no official archive in that partition.
- `526/527` symbols have sealed-holdout archives. `DOSUSDT` has no Binance Vision archive in the holdout partition at acquisition time.
- These gaps do not mutate the frozen roster. Eligibility and period-local gap handling are deferred to Phase 1B.
- Funding is stored in official monthly archive granularity; manifest ranges describe archive partitions, not inferred observation continuity.
- Owner amendment A1 explicitly accepts current-roster survivorship/coverage bias.

## Physical sealing and checks

- Development root: `data/altcoin-multitf-003/development/`.
- Sealed holdout root: `data/altcoin-multitf-003/sealed-holdout/`.
- Metadata: `data/altcoin-multitf-003/metadata/`.
- `sealed-inventory.json` pins every sealed path, size and SHA-256 and pins the manifest hash.
- The research reader denies sealed payload paths.
- Full validation verified path uniqueness, file sizes/hashes, datatype/timeframe, exact half-open partitions and no overlap.
- Holdout payload contents were not opened, unzipped, aggregated or analysed. Acquisition wrote opaque ZIP bytes and computed byte hashes only.
- Heavy raw files remain ignored by Git and are not committed.

Acquisition/data/sealing tests: `7/7 PASS`.

## Decision

**Phase 1A DONE. Phase 1B is ready**, subject to preserving sealed-holdout access denial. Phase 1B may inspect development only, derive higher timeframes from development `5m`, and apply frozen eligibility/gap rules; it must not open holdout payloads.
