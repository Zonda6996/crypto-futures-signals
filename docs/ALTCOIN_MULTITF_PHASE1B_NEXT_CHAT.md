# Prompt для следующего чата — ALT-MULTITF-003 Phase 1A blocked continuation

Продолжи работу в `Zonda6996/crypto-futures-signals`, ветка `v0/altcoin-momentum-analysis-25e7e60d`. Выполни только Phase 1A; Phase 1B и исследования запрещены.

## Сначала

Проверь HEAD/ancestry и полностью прочитай `docs/HANDOFF.md`, `docs/roadmap.md`, `docs/ALTCOIN_MULTITF_FROZEN_PROTOCOL.md`, `reports/ALTCOIN_MULTITF_PHASE1A_ACQUISITION.md`, этот файл, `research/altcoin_multitf_phase1a.py`, `research/altcoin_basket_data.py`, `research/altcoin_phase_a_audit.py`, `research/data.py`, `tests/test_altcoin_multitf_phase1a.py`, `.gitignore`.

## Frozen owner decisions

- A1: current Binance USD-M USDT perpetual roster принят; historical delisted/failed registry не требуется; survivorship/coverage bias принят; roster freeze выполняется до market-data requests и roster никогда не меняется по coverage/results.
- A2: liquidity cohorts `$10m–25m` и `≥$25m`; minimum age `30d`; gaps исключают затронутый period/decision до clean-window recovery, не весь asset; параметры могут различаться по заранее заданным TF-группам, но не symbols; hard safety gates отделены от diagnostic scorecard; development проходит при positive net expectancy, drawdown не хуже `−30%` и устойчивости большинства доступных outer windows. Holdout остаётся одноразовым и строгим.
- Raw `15m/30m/1h/2h/4h/1d` не скачивать: только будущая Phase 1B агрегирует их из `5m`.

## Точный blocker на 2026-08-21T22:08:13Z

- `https://fapi.binance.com/fapi/v1/exchangeInfo` → HTTP 451.
- официальные `fapi1.binance.com` … `fapi4.binance.com` → HTTP 202, empty body (0 bytes).
- Binance Vision market archives не являются current contract metadata snapshot.
- Frozen symbols/files/bytes: `0/0/0`; holdout не создан и не прочитан.

Нужен egress к одному официальному production `GET /fapi/v1/exchangeInfo`, возвращающему непустой JSON. API key не нужен. Не возвращай historical-delisted blocker и не используй сторонний roster.

## После восстановления доступа

1. До market data сохрани полный raw response, URL, UTC acquisition timestamp, byte size, SHA-256 и canonical roster/filter manifest.
2. Freeze только current `TRADING`, `PERPETUAL`, `quoteAsset=USDT`, `marginAsset=USDT`; не меняй roster после coverage.
3. Идемпотентно скачай только raw monthly `5m` klines и funding для development `[2019-09-08, 2026-01-01)` и sealed holdout `[2026-01-01, 2026-08-01)` с official Binance Vision endpoints.
4. Используй физически разные ignored directories, `.part` + atomic rename, retry/backoff, checksum-aware resume и fail-closed conflict handling.
5. Holdout записывай как opaque bytes; после записи разрешены только path/size/bounds/source/hash. Не parse/read/aggregate/analyze.
6. Manifest каждого файла: path, size, SHA-256, source, symbol, datatype, timeframe, requested start/end, acquisition timestamp/status. Official 404 сохраняй как gap, symbol не удаляй.
7. Проверь duplicate path/logical/content, overlap, boundaries, filesystem size/hash, unregistered files и повторный sealed hash inventory.
8. Запусти только acquisition/data/sealing tests. Не выполняй normalization, eligibility, signals, ranking, portfolio, PnL, backtest или grid search.
9. Обнови report/HANDOFF/roadmap/этот handoff, не коммить heavy raw files, commit/push в эту же ветку и остановись.

Phase 1A может стать DONE только при frozen+hashed roster, development acquisition, physically isolated holdout, полном manifest/SHA-256 inventory и прошедших boundary/sealing checks. Иначе оставь точный BLOCKED/FAIL. Phase 1B требует отдельного owner approval даже после PASS 1A.
