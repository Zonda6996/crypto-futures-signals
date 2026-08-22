# ALT-MULTITF-005 — готовый prompt следующему чату

Скопируйте весь блок ниже. Он не даёт разрешения на Phase 3.

```text
Работай в репозитории Zonda6996/crypto-futures-signals только на feature branch v0/causal-signal-engine-baeaef96. Начни с фактического pre-flight: fetch, проверь текущую branch, HEAD, git status и commit history; не доверяй устаревшим status-строкам. Phase 2 implementation recovery основан на commit 8d4d9a7 (после переноса commits с v0/causal-signal-engine-997deb80); затем проверь более новый governance/handoff commit этой ветки и используй фактический tip. Не пушь в main.

Сначала полностью изучи:
- docs/HANDOFF.md
- docs/roadmap.md
- docs/ALTCOIN_MULTITF_COMPACT_PROTOCOL.md
- docs/ALTCOIN_MULTITF_COMPACT_PHASE2_SPEC.md
- docs/ALTCOIN_MULTITF_005_GITHUB_ACTIONS.md
- docs/ALTCOIN_MULTITF_005_PHASE2_NEXT_CHAT.md
- docs/altcoin-multitf-005-blob.json
- reports/ALTCOIN_MULTITF_COMPACT_DATA_PHASE.md
- reports/ALTCOIN_MULTITF_005_PHASE2.md
- reports/artifacts/altcoin-multitf-005-phase2-integration.json
- scripts/restore_altcoin_multitf_005.py
- research/altcoin_multitf_compact.py
- research/altcoin_multitf_phase2.py
- research/altcoin_multitf_phase2_dataset.py
- tests/test_altcoin_multitf_005.py
- tests/test_altcoin_multitf_restore.py
- tests/test_altcoin_multitf_phase2.py
- tests/test_altcoin_multitf_phase2_integration.py

ALT-MULTITF-005 — portable public-Blob data/infrastructure revision ALT-MULTITF-004, не новый dataset и не новый roster. Frozen roster содержит 40 symbols; BTWUSDT остаётся в roster без history и является missing/ineligible. Raw inventory: 3291 files / 568466246 bytes. Normalized manifest SHA-256: 9541bad8793b584f74754828f4abb762e1a75dbfdbb8ae823d3256c9049ce0cf.

Если локальных данных нет, не делай acquisition, rebuild или новый roster selection. Восстанови только публичный release без secret:

python scripts/restore_altcoin_multitf_005.py --metadata docs/altcoin-multitf-005-blob.json --root data

Проверенные release values находятся в metadata file:
- URL: https://kdyewyu0flj9zljt.public.blob.vercel-storage.com/altcoin-multitf-005/665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d.tar.gz
- pathname: altcoin-multitf-005/665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d.tar.gz
- size: 1541152490
- SHA-256: 665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d
- access: public; BLOB_READ_WRITE_TOKEN запрещён и не нужен.

При mismatch metadata/schema/size/SHA-256, unsafe archive member, manifest mismatch, unexpected protocol/partition или holdout-like path остановись fail closed до исследования. Не коммить data, archive, caches или временные файлы.

Подтверждённый Phase 2 verdict: PASS / DONE / STOP BEFORE STRATEGY EVALUATION. Causal engine использует только closed bars и опубликованный funding, half-open eligibility до features/ranking, frozen short/medium/long parameters, deterministic score ranking и schema-only portfolio candidates. Real-data checks использовали mechanical timestamps 1767139200000 и 1767225599999 для 5m/1h/1d. Deterministic integration digest: 89e6b3ebfbaeb869dbbdfe284c3aa4017c6ea7230d96ee031e69a6f8661aee4b. Artifact не содержит PnL/backtest fields.

Известные ограничения: universe выбран по текущей ликвидности и несёт survivorship/current-selection bias; BTWUSDT не имеет history; representative integration не является exhaustive market evaluation; causal correctness и deterministic digest не доказывают predictive power, profitability или trading edge. Старые FAIL-ветки ALT-XSMOM-001-B и ETH TEST закрыты и не должны переоткрываться.

Сначала только повтори безопасные tests и сопоставь committed evidence. Не создавай, не перечисляй, не загружай и не читай holdout. Не меняй frozen roster, TF groups, feature parameters или eligibility. Не повторяй acquisition/rebuild.

OWNER APPROVAL REQUIRED — STOP HERE:
[OWNER MUST INSERT AN EXPLICIT APPROVAL LIMITED TO PREPARING THE FROZEN PHASE 3 SPECIFICATION]

Без заполненного owner approval не начинай Phase 3 и не создавай её спецификацию. Даже после approval разрешена только документационная immutable Phase 3 strategy-evaluation specification: заранее один portfolio/execution contract, DEVELOPMENT/TRAIN/VALIDATION calendar, costs/funding, metrics, falsification gates, multiple-testing budget и machine-artifact schema. После документа снова остановись.

Это approval не разрешает реализацию strategy evaluation, parameter/grid search, candidate selection, weights/sizing, orders/trades, PnL, Sharpe/Sortino/Calmar/drawdown, backtest/walk-forward, holdout, paper или live trading. Любые расчёты и реализация требуют следующего отдельного явного owner approval. В финале сообщи фактические branch/commit/status, tests и ровно один разрешённый следующий шаг.
```
