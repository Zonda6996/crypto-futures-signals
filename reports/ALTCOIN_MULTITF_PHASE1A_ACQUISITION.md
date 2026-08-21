# ALT-MULTITF-003 — Phase 1A acquisition gate

Статус: **BLOCKED — OFFICIAL CURRENT ROSTER UNAVAILABLE FROM EXECUTION ENVIRONMENT**

Дата проверки: 21 августа 2026 года, `2026-08-21T22:08:13Z` UTC

Ветка: `v0/altcoin-momentum-analysis-25e7e60d`

Исходный HEAD: `6b904bc6c904b6d6e7a66268ec4dc441fc86c15e`

## Scope и утверждённые правила

Owner amendment A1 принят без пересмотра: используется только current Binance USD-M USDT perpetual roster; полный registry delisted/failed contracts не требуется; survivorship/coverage bias принят; roster обязан быть заморожен до market-data acquisition и не может меняться по coverage.

Также восстановлены ранее утверждённые owner-правила: две liquidity cohorts (`$10m–25m`, `≥$25m`), минимальный возраст `30d`, gaps исключают затронутый период, а не актив навсегда, параметры могут различаться только по TF-группам и не по symbols, hard safety gates отделены от diagnostic scorecard, development требует положительной net expectancy, приемлемого drawdown и устойчивости большинства окон. Holdout остаётся одноразовым и строгим.

## Проверка официального current roster

До любых запросов market data проверены только официальные production Binance USD-M metadata endpoints:

| URL | Результат |
|---|---|
| `https://fapi.binance.com/fapi/v1/exchangeInfo` | HTTP `451`, response body недоступен |
| `https://fapi1.binance.com/fapi/v1/exchangeInfo` | HTTP `202`, пустой body (`0` bytes) |
| `https://fapi2.binance.com/fapi/v1/exchangeInfo` | HTTP `202`, пустой body (`0` bytes) |
| `https://fapi3.binance.com/fapi/v1/exchangeInfo` | HTTP `202`, пустой body (`0` bytes) |
| `https://fapi4.binance.com/fapi/v1/exchangeInfo` | HTTP `202`, пустой body (`0` bytes) |

Binance Vision предоставляет официальные symbol-addressed market archives, но не официальный current `exchangeInfo` snapshot с contract type/status/quote/margin/filter metadata. Поэтому Vision listing нельзя подменить требуемым current roster snapshot. Historical-delisted blocker не возвращён и не применяется.

## Fail-closed verdict

Получить непустой официальный current roster response из окружения невозможно. Следовательно, нельзя доказательно:

- сохранить полный raw metadata response и его SHA-256;
- зафиксировать окончательный список symbols до market-data download;
- скачать market data без риска самовольно сконструированного roster.

В соответствии с явным условием задачи acquisition остановлен на roster gate. Нужен сетевой доступ хотя бы к одному официальному production endpoint `GET /fapi/v1/exchangeInfo` с непустым JSON response (напрямую либо через разрешённый egress в поддерживаемом регионе). Никакие API keys не требуются.

## Фактический inventory

- Frozen symbols: `0` — snapshot не получен.
- Raw market files: `0`.
- Raw market bytes: `0`.
- Development range, запрошенный protocol: `[2019-09-08T00:00:00Z, 2026-01-01T00:00:00Z)`; не скачан.
- Holdout range, запрошенный protocol: `[2026-01-01T00:00:00Z, 2026-08-01T00:00:00Z)`; не скачан и не открыт.
- Sealed holdout directory: не создан, потому что roster gate предшествует любому download.
- Manifest/SHA-256 inventory: market-file inventory отсутствует, так как файлов нет.
- Gaps: не измерялись; без frozen roster это было бы coverage analysis и нарушило бы ordering gate.
- Holdout reads/parsing/aggregation: `0`.
- Normalization, eligibility, signals, ranking, portfolio, PnL, backtest, grid search: не выполнялись.

## Код и проверки

`research/altcoin_multitf_phase1a.py` теперь реализует amendment A1: разрешает только официальный непустой current `exchangeInfo`, детерминированно выбирает `TRADING/PERPETUAL/USDT quote/USDT margin`, хеширует raw response, отвергает unofficial/empty/invalid/duplicate roster и сохраняет существующие half-open boundaries, atomic idempotent writes, sealed read denial и filesystem checksum audit. Historical lifecycle/delisted evidence больше не является gate.

**Phase 1A = BLOCKED, NOT DONE. Phase 1B = NOT READY.** Повторный запуск должен начинаться с получения и immutable freeze официального current roster; до этого market-data acquisition запрещён.
