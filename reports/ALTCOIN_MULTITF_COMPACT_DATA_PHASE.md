# ALT-MULTITF-004 — compact data phase

Дата: 22 августа 2026 года
Статус: **DONE / STOP перед Phase 2**

## Что сделано

После утраты незакоммиченных payload `ALT-MULTITF-003` создан новый protocol ID без переписывания старого эксперимента. До market-history acquisition сохранены официальные raw snapshots Binance USD-M `exchangeInfo` и `ticker/24hr`; затем заморожены ровно 40 текущих USDT perpetual altcoin contracts по убыванию числового 24h `quoteVolume`, с tie-break по symbol. `BTCUSDT` и `ETHUSDT` заранее исключены.

Frozen roster: `XRPUSDT`, `SOLUSDT`, `ZECUSDT`, `HYPEUSDT`, `TRUMPUSDT`, `DOGEUSDT`, `ENAUSDT`, `1000PEPEUSDT`, `BNBUSDT`, `SUIUSDT`, `ADAUSDT`, `BCHUSDT`, `PUMPUSDT`, `LINKUSDT`, `WLDUSDT`, `NEARUSDT`, `ASTERUSDT`, `AAVEUSDT`, `BEATUSDT`, `TAOUSDT`, `AVAXUSDT`, `ONDOUSDT`, `WLFIUSDT`, `HEMIUSDT`, `UNIUSDT`, `PENGUUSDT`, `1000SHIBUSDT`, `XLMUSDT`, `ONGUSDT`, `LTCUSDT`, `LITUSDT`, `DASHUSDT`, `GALAUSDT`, `FILUSDT`, `ETCUSDT`, `ACEUSDT`, `BOMEUSDT`, `TUTUSDT`, `BTWUSDT`, `POLUSDT`.

Selection по текущей ликвидности создаёт survivorship/current-selection bias. `BTWUSDT` не имел development archives, но сохранён во frozen roster и помечен как missing/ineligible, а не удалён.

## Raw development acquisition

Диапазон: `[2020-01-01T00:00:00Z, 2026-01-01T00:00:00Z)`. Скачивались только official monthly Binance Vision USD-M `5m` klines и funding-rate ZIP; отдельные higher-TF archives не скачивались.

- raw development files: **3 291**;
- raw bytes: **568 466 246**;
- symbols с хотя бы одной development history: **39/40**;
- полный raw manifest SHA-256: `224f644989d569c4d9d647dc27aab58aaf1382db35a21e9cb6eeac0b380abe78`;
- повторная filesystem verification: **3 291/3 291 совпали, 0 mismatches**.

Safe resume использует атомарные `.part` downloads, существующий файл принимается только при совпадении ожидаемого размера и SHA-256. ZIP traversal, multiple payload members, boundaries и конфликтующие duplicates fail closed.

## Normalization и aggregation

Получено **312** normalized files / **973 181 163 bytes**. Строки:

| datatype / TF | rows |
|---|---:|
| 5m klines | 14 276 432 |
| funding | 168 371 |
| 15m | 4 758 808 |
| 30m | 2 379 401 |
| 1h | 1 189 692 |
| 2h | 594 834 |
| 4h | 297 407 |
| 1d | 49 548 |

Все higher TF построены исключительно из полных UTC-aligned `5m` buckets. Неполные buckets не публиковались; close timestamp равен close последнего входящего `5m` bar, поэтому bar нельзя использовать раньше его полного закрытия.

Quality inventory:

- gaps `>30m`: **18**;
- exact duplicate rows: **0**;
- conflicting duplicates: **0**;
- invalid schema/numeric/OHLC/boundary rows: **0**;
- out-of-order rows: **0**;
- missing development histories: **1 (`BTWUSDT`)**.

## Causal eligibility

На каждом decision timestamp применены: age `>=30d`, trailing 30d coverage `>=99%`, отсутствие gap `>30m` до восстановления clean trailing window, 30 полных UTC-дней и median causal daily quote volume. Cohorts не зависят от будущих результатов: `$10m–25m`, `>=25m`, иначе ineligible.

| TF | decisions | $10m–25m | >=$25m | ineligible | eligible coverage |
|---|---:|---:|---:|---:|---:|
| 5m | 14 288 252 | 1 020 096 | 11 847 744 | 1 420 412 | 90.06% |
| 15m | 4 762 748 | 340 032 | 3 949 248 | 473 468 | 90.06% |
| 30m | 2 381 371 | 170 016 | 1 974 624 | 236 731 | 90.06% |
| 1h | 1 190 678 | 85 008 | 987 312 | 118 358 | 90.06% |
| 2h | 595 327 | 42 504 | 493 656 | 59 167 | 90.06% |
| 4h | 297 654 | 21 252 | 246 828 | 29 574 | 90.06% |
| 1d | 49 590 | 3 542 | 41 138 | 4 910 | 90.10% |

Eligibility audit содержит **337 contiguous state runs**. Разница между normalized row count и decision inventory объясняется тем, что decision timeline учитывает все frozen symbols и периодические exclusions/availability; это audit eligibility, а не сигнал или backtest.

## Boundaries и ограничения

- Holdout directory не создавался; holdout **не скачивался, не перечислялся, не хешировался и не читался**.
- Signals, ranking, portfolio construction, PnL, backtest и grid search: **0 запусков**.
- Frozen roster не менялся по coverage, возрасту, gaps или будущим данным.
- Это compact exploratory current-liquidity universe, а не point-in-time historical universe.
- Raw/normalized payload и machine manifests находятся под `data/altcoin-multitf-004/` и исключены из Git; отчёт содержит воспроизводимые totals и manifest digest.

## Verdict

Data phase **DONE**: acquisition, SHA-256 verification, normalization, causal aggregation, quality inventory и eligibility audit завершены. **Phase 2 не начата и не разрешена автоматически**; следующий чат может реализовать causal engine только после отдельного owner approval и без strategy selection.
