# ALT-MULTITF-004 — следующий чат

Текущий статус: **DATA PHASE DONE / Phase 2 NOT APPROVED**.

Перед работой прочитать:

- `docs/ALTCOIN_MULTITF_COMPACT_PROTOCOL.md`;
- `reports/ALTCOIN_MULTITF_COMPACT_DATA_PHASE.md`;
- `research/altcoin_multitf_compact.py`;
- `docs/HANDOFF.md` и `docs/roadmap.md`.

Frozen roster: 40 symbols из report; менять его по coverage, liquidity или результатам запрещено. `BTWUSDT` остаётся в roster и ineligible из-за отсутствия development archives.

Development machine data ожидаются в `data/altcoin-multitf-004/`; raw manifest digest — `224f644989d569c4d9d647dc27aab58aaf1382db35a21e9cb6eeac0b380abe78`. Перед использованием выполнить `python3 -m research.altcoin_multitf_compact verify --root data`. Если payload отсутствует в новом sandbox, не выдавать Phase 2 за воспроизводимую: raw/normalized data намеренно не коммитятся.

Phase 2 может быть только отдельным owner-approved scope: causal engine implementation и tests без parameter selection. Signals, strategy ranking, portfolio construction, PnL, backtest, grid search и prospective validation/holdout запрещены до следующих gates. Holdout для `ALT-MULTITF-004` пока не существует и не должен создаваться автоматически.
