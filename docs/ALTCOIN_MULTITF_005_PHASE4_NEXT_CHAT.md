# ALT-MULTITF-005 — prompt для следующего аккаунта (Phase 4 completion)

Скопируйте весь блок ниже в новый чат. Он разрешает продолжить только незавершённую research-валидацию; holdout и paper/live по-прежнему запрещены.

```text
Работай в репозитории Zonda6996/crypto-futures-signals на текущей feature branch, не пушь в main. Сначала сделай pre-flight: fetch, branch, HEAD, git status, recent history. Не доверяй старым branch/commit строкам из документации — используй фактический tip.

Сначала полностью прочитай:
- docs/HANDOFF.md
- docs/roadmap.md
- docs/ALTCOIN_MULTITF_COMPACT_PROTOCOL.md
- docs/ALTCOIN_MULTITF_005_PHASE3_SPEC.md
- reports/ALTCOIN_MULTITF_005_PHASE3_PROFITABILITY.md
- reports/ALTCOIN_MULTITF_005_ASSET_TF_EXAMPLES.md
- reports/artifacts/altcoin-multitf-005-phase3/verdict.json
- research/altcoin_multitf_phase3.py
- tests/test_altcoin_multitf_phase3.py

Если dataset локально отсутствует, восстанови только verified public release canonical restore-командой из docs/altcoin-multitf-005-blob.json. Не делай новый acquisition, roster selection или rebuild. Проверяй archive size/SHA-256, safe extraction и normalized manifest fail-closed. Не коммить data, archive, caches или временные файлы.

Frozen facts:
- protocol: ALT-MULTITF-005-PHASE3-FROZEN-1;
- manifest SHA-256: 7ec1d163171aa0a825ee1cb3c8eaece9e8d9ec749928b8be9d58990f0976b321;
- full manifest: 58 140 configs = Family A 3 060 + Family B 55 080;
- Family A полностью рассчитана: 3 060/3 060;
- текущий лучший A: f48bdca64b00d0903b54, daily-proxy net +79,24%, annualized +10,20%, Sharpe 1,465, max drawdown −5,68%, positive outer folds 4/5;
- Family B: 0/55 080;
- official verdict: NO WINNER;
- holdout не открывался и должен остаться untouched.

OWNER APPROVAL FOR THIS CHAT:
Разрешаю Phase 4 completion только на DEVELOPMENT: реализовать нативный multi-timeframe replay, полностью рассчитать frozen Family B, повторно оценить Family A там, где текущий daily proxy не соответствует frozen TF semantics, выполнить заранее обязательные SPA/Deflated Sharpe и frozen robustness/concentration gates. Разрешаю оптимизацию производительности, deterministic checkpoints/resume и машинные артефакты. Не разрешаю менять manifest, roster, calendar, costs, thresholds или grid после просмотра результатов.

Обязательные задачи:
1. Аудит текущего Phase 3 кода и артефактов; сохранить существующий NO WINNER как historical checkpoint, не переписывать его задним числом.
2. Реализовать TF-native causal loader/replay для 15m/30m/1h/2h/4h/1d с closed-bar signals и исполнением не раньше следующего open. Не округлять 6h/12h holding/rebalance до суток.
3. Добавить participation/liquidity enforcement на нативных volume bars, комиссии 0,05% на сторону, base slippage 0,02% на сторону, stress 0,05% на сторону и publication-time funding.
4. Полностью рассчитать frozen Family B 55 080/55 080 и пересчитать затронутые Family A configs без расширения grid. Нужны deterministic chunking/checkpoints и resume; partial run не может получить PASS.
5. Выполнить Hansen SPA 5%, Deflated Sharpe 95%, fold stability, parameter-neighborhood, concentration, cost/funding/slippage и liquidity robustness строго по frozen spec.
6. Выбрать максимум одного development winner на family только при прохождении всех gates. Если family не прошла — явно NO WINNER для неё.
7. Не читать, не перечислять и не загружать holdout-like paths. Добавить/сохранить fail-closed tests.
8. Обновить reports, machine artifacts, docs/HANDOFF.md и docs/roadmap.md. Создать prompt следующего чата только для shortlist freeze/one-time holdout approval; сам holdout не открывать.

Definition of done:
- native TF semantics подтверждены тестами;
- A и B завершены на 100%, иначе verdict INCOMPLETE/NO WINNER;
- SPA/DSR и все mandatory gates имеют воспроизводимые machine outputs;
- никаких holdout reads;
- итог объяснён владельцу простыми словами: что рассчитано, что получилось, PASS/FAIL/NO WINNER, риски и ровно один следующий разрешённый шаг.

Запрещено: менять frozen hypothesis budget, подбирать новые thresholds после результатов, скрывать отрицательные configs, называть daily proxy нативным multi-TF, открывать holdout, начинать paper/live trading или использовать реальные деньги.
```

## Что будет выполняться в этой фазе

1. **Исправление главного ограничения:** движок действительно будет использовать свечи выбранного TF, а не дневной proxy.
2. **Полный второй класс стратегий:** будут рассчитаны все 55 080 вариантов Family B с TP/SL и точным внутридневным исполнением.
3. **Проверка на случайную удачу:** SPA и Deflated Sharpe оценят, не появился ли красивый результат просто из-за перебора десятков тысяч вариантов.
4. **Проверка реалистичности:** комиссии, funding, slippage, volume/participation и стресс-сценарии будут применены на нативных барах.
5. **Механический вердикт:** итогом будет либо максимум один кандидат на каждое семейство, либо честный NO WINNER. Holdout останется закрытым.
