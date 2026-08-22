# ALT-MULTITF-005 — handoff после Phase 2

Статус: **DATA RELEASE VERIFIED / PHASE 2 PASS / STOP BEFORE PHASE 3**.

## Что подтверждено

- Public Blob восстановлен анонимно canonical CLI.
- Archive size/SHA-256, safe extraction и normalized manifest verification прошли.
- Frozen roster/inventory не менялись; `BTWUSDT` сохранён как missing/ineligible.
- Bounded real-data loader и short/medium/long causal integration прошли.
- Focused results: **15 Phase 2 tests PASS**, **10 release/restore tests PASS**.
- Evidence: `reports/artifacts/altcoin-multitf-005-phase2-integration.json`.
- Holdout не создавался и не читался; parameter search, execution, sizing, PnL и backtest не запускались.

PASS здесь означает только deterministic causal implementation и leakage-safe data access. Он не означает наличие торгового edge.

## Промпт следующему чату

> Работай в `Zonda6996/crypto-futures-signals` на feature branch, содержащей ALT-MULTITF-005 Phase 2. Сначала прочитай `docs/HANDOFF.md`, `docs/roadmap.md`, `docs/ALTCOIN_MULTITF_COMPACT_PROTOCOL.md`, `docs/ALTCOIN_MULTITF_COMPACT_PHASE2_SPEC.md`, `reports/ALTCOIN_MULTITF_COMPACT_DATA_PHASE.md`, `research/altcoin_multitf_phase2.py`, `research/altcoin_multitf_phase2_dataset.py`, `tests/test_altcoin_multitf_phase2.py`, `tests/test_altcoin_multitf_phase2_integration.py` и `reports/artifacts/altcoin-multitf-005-phase2-integration.json`. Подтверди branch/commit и повтори focused tests. Не читай и не создавай holdout.
>
> Текущий gate — только owner decision о **документационной Phase 3**. Без отдельного явного approval остановись после аудита. Если owner разрешит подготовку Phase 3, создай новый immutable strategy-evaluation protocol до любых расчётов: один заранее заданный portfolio construction/execution contract, календарь DEVELOPMENT/TRAIN/VALIDATION, cost/funding model, метрики, falsification gates, multiple-testing budget и machine-artifact schema. Specification должна отдельно запретить grid search, selection по уже просмотренным результатам и использование holdout.
>
> После документационной спецификации снова остановись и запроси отдельное разрешение на реализацию/расчёт. Не запускай parameter search, candidate selection, portfolio execution, sizing, PnL или backtest в том же approval. Не меняй frozen roster, TF groups, feature parameters, eligibility rules или release data. Не открывай старые FAIL-ветки `ALT-XSMOM-001-B` и ETH TEST.

## Recovery path

Если release data отсутствует локально, восстанови его только командой:

```bash
python scripts/restore_altcoin_multitf_005.py --metadata docs/altcoin-multitf-005-blob.json --root data
```

Restore не требует секрета. При любом mismatch size/SHA-256, unsafe member, manifest mismatch, schema/boundary violation или holdout-like path — fail closed, зафиксировать ошибку и остановиться без исследования.

## Ровно один следующий шаг

Получить решение владельца: разрешить или отклонить **только подготовку frozen Phase 3 specification**. Реализация и расчёты требуют следующего отдельного gate.
