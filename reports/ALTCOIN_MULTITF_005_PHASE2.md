# ALT-MULTITF-005 — Phase 2 causal engine

Дата проверки: 22 августа 2026 года

Verdict: **PASS / PHASE 2 DONE / STOP BEFORE STRATEGY EVALUATION**

## Scope и смысл результата

`ALT-MULTITF-005` — переносимая public-Blob revision данных `ALT-MULTITF-004`, а не новый dataset, новый roster или evidence торгового edge. Phase 2 реализует и проверяет только deterministic causal features, cross-sectional ranking, diagnostics и schema-only portfolio candidates. Parameter search, weights, sizing, orders, trades, costs, PnL, backtest, walk-forward, paper/live trading и holdout не запускались.

## Restore и release contract

Canonical restore:

```bash
python scripts/restore_altcoin_multitf_005.py --metadata docs/altcoin-multitf-005-blob.json --root data
```

- URL: `https://kdyewyu0flj9zljt.public.blob.vercel-storage.com/altcoin-multitf-005/665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d.tar.gz`
- pathname: `altcoin-multitf-005/665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d.tar.gz`
- archive size: `1541152490` bytes
- archive SHA-256: `665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d`
- access: public; `BLOB_READ_WRITE_TOKEN` не требуется
- anonymous full-download verification: PASS
- safe extraction и per-file normalized-manifest verification: PASS
- normalized manifest SHA-256: `9541bad8793b584f74754828f4abb762e1a75dbfdbb8ae823d3256c9049ce0cf`

В проверенном restore были подтверждены все manifest entries. Holdout directory/path отсутствовал; loader отклоняет holdout-like dataset path или timeframe до чтения.

## Dataset inventory и ограничения

- frozen roster: 40 symbols;
- raw inventory: 3 291 files / 568 466 246 bytes;
- normalized inventory: 312 files / 973 181 163 bytes;
- missing history: только `BTWUSDT`, сохранён во frozen roster и обработан как missing/ineligible;
- normalized rows: 14 276 432 (5m), 4 758 808 (15m), 2 379 401 (30m), 1 189 692 (1h), 594 834 (2h), 297 407 (4h), 49 548 (1d), funding 168 371.

Universe был выбран по текущей ликвидности до acquisition. Поэтому остаются survivorship/current-selection bias; это не point-in-time historical universe.

## Реализованная Phase 2

Frozen TF groups и параметры:

| group | timeframes | momentum | volatility returns | trend closes | funding publications |
|---|---|---:|---:|---:|---:|
| short | 5m, 15m, 30m | 12 | 24 | 48 | 3 |
| medium | 1h, 2h, 4h | 6 | 12 | 24 | 3 |
| long | 1d | 5 | 10 | 20 | 3 |

Engine использует только bars с `close_time_ms <= T`, только funding с `publication_time_ms <= T`, half-open eligibility `[start_ms, end_exclusive_ms)` и применяет eligibility до feature calculation/ranking. Реализованы one-bar log return, momentum, population volatility, normalized momentum, trend, funding sum и `ranking_input = normalized_momentum * trend - funding`. Ranking детерминирован: score DESC, затем symbol ASC; diagnostics и schema-only candidates не содержат execution/PnL.

Bounded adapter `research/altcoin_multitf_phase2_dataset.py` читает только необходимые хвосты normalized development CSV, валидирует protocol/schema/timestamps/prices и не изменяет dataset.

## Real-data integration evidence

Machine artifact: `reports/artifacts/altcoin-multitf-005-phase2-integration.json`.

Проверены mechanically selected timestamps `1767139200000` и `1767225599999` для representative `5m`, `1h`, `1d`. На каждом check: 40 input, 33 eligible/featured, 7 excluded (`ACEUSDT`, `BOMEUSDT`, `BTWUSDT`, `HEMIUSDT`, `LITUSDT`, `ONGUSDT`, `TUTUSDT`).

Deterministic output SHA-256:

`89e6b3ebfbaeb869dbbdfe284c3aa4017c6ea7230d96ee031e69a6f8661aee4b`

## Tests

В исходном restored-data verification были зафиксированы 15 Phase 2 unit/integration PASS и 10 release/restore PASS. При recovery на этой ветке выполнено:

```bash
python -m unittest tests.test_altcoin_multitf_005 -v
python -m unittest tests.test_altcoin_multitf_phase2 -v
python -m unittest discover -s tests -v
```

Результат recovery: focused set 17/17 PASS; полный suite 151 PASS, 0 FAIL, 2 SKIP. Два real-data tests пропущены, потому что многогигабайтный dataset намеренно не скачивался повторно в новом sandbox; committed machine artifact и manifest digest относятся к ранее успешно завершённому restored-data run.

Покрыты no-future mutation, higher-TF close boundary, rolling-window off-by-one, funding publication boundary, eligibility-before-ranking, half-open eligibility, missing `BTWUSDT`, tie-break, symbol-order invariance, TF-group isolation, zero volatility, invalid prices/timestamps, overlap eligibility, holdout rejection и отсутствие execution/PnL schema.

## Известные ограничения

1. Causal correctness не доказывает predictive power или trading edge.
2. Current-liquidity universe несёт survivorship/current-selection bias.
3. Representative integration проверяет по одному TF на группу, а не каждую возможную дату/TF.
4. Dataset не хранится в Git; новый sandbox должен восстанавливать его только canonical public restore.
5. Любой strategy evaluation требует нового immutable protocol и отдельного owner approval.

## Governance

Разрешён только read-only audit evidence и подготовка отдельной frozen Phase 3 specification после явного owner approval. До следующего gate строго запрещены parameter/grid search, изменение roster/feature parameters, portfolio construction/execution, sizing, costs, PnL, backtest/walk-forward, создание/чтение holdout и paper/live trading.

**Phase 2 технически завершена, но торговый edge ещё не проверялся.**
