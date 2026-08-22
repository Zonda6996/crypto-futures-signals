# ALT-MULTITF-005 — следующий чат после публикации

Статус до реального успешного GitHub Actions run: **INFRASTRUCTURE READY / DATA RELEASE NOT YET VERIFIED**.

Нельзя заполнять URL, SHA-256 и размер предположениями. После run со статусом `Anonymous full-download verification: PASS` скачайте release artifact, сохраните `verified-release.json` как `docs/altcoin-multitf-005-blob.json` и закоммитьте его. Только тогда новый чат может восстановить dataset без секрета.

## Промпт для следующего аккаунта после PASS

> Работай в `Zonda6996/crypto-futures-signals` с commit, содержащим `docs/altcoin-multitf-005-blob.json`. Сначала прочитай `docs/HANDOFF.md`, `docs/ALTCOIN_MULTITF_005_GITHUB_ACTIONS.md`, этот файл и verified metadata. Восстанови ALT-MULTITF-005 командой `python scripts/restore_altcoin_multitf_005.py --metadata docs/altcoin-multitf-005-blob.json --root data`; Blob Public, секрет для restore не нужен. Проверь, что restore прошёл size/SHA-256, safe extraction и normalized manifest verification. Не переизбирай frozen roster, не меняй данные и не читай/создавай holdout. Не запускай signal/PnL/backtest/parameter search без отдельной утверждённой frozen Phase 2 specification. Сначала сообщи подтверждённые protocol ID, URL/pathname, size, SHA-256, source commit и manifest result из файлов, затем остановись у следующего gate.

ALT-MULTITF-005 является data/infrastructure revision ALT-MULTITF-004, а не новым результатом стратегии. Публичность Blob означает доступность архива, а не доказательство edge.
