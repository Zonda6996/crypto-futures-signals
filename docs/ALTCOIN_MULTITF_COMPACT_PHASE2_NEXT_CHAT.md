# ALT-MULTITF-004 — следующий gate

Текущий статус: **PHASE 2 DONE / STOP перед strategy evaluation**.

## Frozen state

- roster: неизменяемые 40 symbols из data-phase report; `BTWUSDT` остаётся ineligible при отсутствии history;
- development: `[2020-01-01, 2026-01-01)`;
- raw inventory: 3 291 files / 568 466 246 bytes;
- historical data-phase raw manifest digest: `224f644989d569c4d9d647dc27aab58aaf1382db35a21e9cb6eeac0b380abe78`;
- portable bundle metadata: `docs/altcoin-multitf-004-blob.json`;
- restore: `python3 -m scripts.restore_altcoin_multitf_004 --root data`, затем `python3 -m research.altcoin_multitf_compact verify --root data`;
- Phase 2 specification: `docs/ALTCOIN_MULTITF_COMPACT_PHASE2_SPEC.md`;
- implementation: `research/altcoin_multitf_phase2.py`.

Restore использует project `BLOB_READ_WRITE_TOKEN`, проверяет размер и SHA-256 всего tar bundle до безопасной extraction. Private Blob содержит только публичные Binance market archives и derived development artifacts. Frozen roster не пересобирается.

## Completed Phase 2

Реализованы causal closed-bar returns, rolling momentum, volatility normalization, trend filter, publication-time funding alignment, eligibility-before-ranking, deterministic cross-sectional ranking input, schema-only portfolio candidates, safety gates и diagnostics. Параметры различаются только между short (`5m/15m/30m`), medium (`1h/2h/4h`) и long (`1d`) groups.

Не реализованы и не запускались: parameter selection, portfolio construction execution, PnL, Sharpe/Sortino, drawdown, backtest, walk-forward и holdout/prospective reads. Holdout для protocol физически не существует.

## Next gate

Остановиться. Strategy evaluation возможна только после отдельного owner approval и нового frozen evaluation specification. Нельзя менять Phase 2 parameters по symbol, открывать/создавать holdout либо выбирать лучшую стратегию без следующего gate.
