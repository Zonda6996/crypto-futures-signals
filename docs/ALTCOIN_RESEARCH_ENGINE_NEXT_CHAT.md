# Handoff: ALTCOIN Research Engine — Phase 0

Скопируйте текст ниже в новый чат.

```text
Продолжи работу в репозитории Zonda6996/crypto-futures-signals,
ветка v0/altcoin-momentum-analysis-25e7e60d.

ЦЕЛЬ: выполнить только Phase 0 нового ALTCOIN Research Engine — полностью
зафиксировать исследовательский протокол до кода, скачивания данных и расчётов.

Сначала полностью прочитай:
- docs/HANDOFF.md
- docs/roadmap.md
- docs/ALTCOIN_LONG_ONLY_PROTOCOL.md
- docs/ALTCOIN_RESEARCH_ENGINE_PROTOCOL.md
- reports/ALTCOIN_LOMOM_PHASE3_TRAIN.md
- research/altcoin_long_only_engine.py
- research/altcoin_long_only_run.py
- tests/test_altcoin_long_only.py

Также read-only изучи архитектуру github.com/Zonda6996/SMC-RESEARCH-ENGINE,
но не копируй его результаты и не меняй тот репозиторий.

КОНТЕКСТ:
- ALT-XSMOM-001-B окончательно FAIL / STOP.
- ALT-LOMOM-002-A завершил TRAIN с diagnostic PASS, но это contaminated
  DEVELOPMENT/TRAIN evidence на fixed basket с survivorship/selection bias.
- ALT-LOMOM-002-A остаётся неизменяемым baseline.
- Владелец разрешил новый контролируемый широкий исследовательский цикл.
- Binance USD-M perpetuals, primary lifecycle universe.
- Два независимых семейства: portfolio signals и trade signals с TP/SL.
- TF: 5m, 15m, 30m, 1h, 2h, 4h, 1d.
- Профиль риска умеренный.
- Отбор через nested walk-forward.
- Данные 2026 года должны стать новым sealed untouched holdout.

ЧТО СДЕЛАТЬ В PHASE 0:
1. Не писать engine и не запускать backtest.
2. Проверить план на неоднозначности.
3. Запросить решения владельца по каждому незаданному числу, включая:
   - точный snapshot_end sealed holdout;
   - listing age, liquidity/volume и data-completeness eligibility;
   - точные folds, purge и embargo;
   - точный конечный search space Trade family: ATR/vol multiples,
     take ladders, trailing/time exits, re-entry и circuit breaker;
   - costs/slippage/funding и participation tiers;
   - score, multiple-testing correction и mechanical PASS/FAIL;
   - правила tie-break и freeze shortlist.
4. После ответов создать frozen protocol ID/version и machine-readable manifests.
5. Зафиксировать HOLDOUT guard contract, но не читать holdout rows.
6. Обновить docs/HANDOFF.md и docs/roadmap.md.
7. Запустить только проверки документации/manifest schema, если они не требуют
   market data или backtest.
8. Закоммитить и запушить изменения в эту же ветку.
9. Остановиться после Phase 0.

ЖЁСТКИЕ ОГРАНИЧЕНИЯ:
- Не менять и не перезапускать ALT-LOMOM-002-A.
- Не скачивать, не открывать и не анализировать данные 2026 holdout.
- Не выполнять sweep, backtest, TRAIN, VALIDATION или paper/live trading.
- Не добавлять параметры после просмотра результатов.
- Portfolio и Trade family не смешивать в одном leaderboard.
- Lifecycle universe должен включать delisted contracts и point-in-time eligibility.
- Если протокол неоднозначен, спрашивать владельца, а не выбирать трактовку.

После завершения объясни простыми словами:
- что именно зафиксировано;
- какие варианты будут тестироваться;
- как защищаемся от подгонки;
- какие данные запечатаны;
- что разрешено в Phase 1 и что всё ещё запрещено.
```

Текущий документ является инструкцией, а не разрешением начать Phase 1. Phase 0 должна закончиться новым owner gate.
