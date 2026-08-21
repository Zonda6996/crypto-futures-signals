# Prompt for the next chat — exploratory fixed-basket Phase B

Продолжи работу в репозитории `Zonda6996/crypto-futures-signals`, ветка `v0/crypto-futures-analysis-88d9d19a`.

Сначала прочитай полностью:

- `docs/ALTCOIN_PROTOCOL.md`
- `reports/ALTCOIN_PHASE_A_DATA_AUDIT.md`
- `docs/HANDOFF.md`
- `docs/roadmap.md`

## Неизменяемый контекст

Старая ETH-стратегия окончательно получила единственный TEST 2025 `FAIL`. Никогда не запускай этот TEST повторно, не меняй параметры старой стратегии и не используй её TEST для настройки новой гипотезы.

Строгий altcoin Phase A для point-in-time Top 30 получил `STOP`, потому что отсутствует полный исторический lifecycle registry Binance USD-M perpetuals с delisted-контрактами. Этот verdict не отменён.

Владелец явно разрешил отдельный упрощённый exploratory experiment `ALT-XSMOM-001-B` с осознанным survivorship/selection bias. Frozen basket нельзя менять:

1. `ETHUSDT`
2. `BNBUSDT`
3. `SOLUSDT`
4. `XRPUSDT`
5. `ADAUSDT`
6. `DOGEUSDT`
7. `LINKUSDT`
8. `LTCUSDT`
9. `AVAXUSDT`
10. `DOTUSDT`

HOLDOUT начинается `2026-01-01T00:00:00Z` и полностью закрыт. Не загружай и не запрашивай bars, funding, metadata или любые производные данные с timestamp `>= 2026-01-01T00:00:00Z`.

## Ровно одна задача

Выполни exploratory Phase B только на frozen basket:

1. Проверь доступность, дубли, монотонность timestamps и hourly coverage pre-HOLDOUT bars/funding по каждому контракту.
2. Не заменяй отсутствующий актив другим. Актив становится eligible после 90 дней собственной истории и при coverage не ниже 95% за trailing 30 дней. Cross-section допустим минимум при 5 eligible активах.
3. До расчёта returns зафиксируй TRAIN/VALIDATION границы, исходя только из общей coverage и календаря, не из performance. Запиши amendment/phase protocol и hashes входов.
4. Реализуй causal cross-sectional long/short momentum только в уже разрешённой сетке: horizons 7/14/30 дней, rebalance 8h/12h/24h, next-bar execution. При 5–9 eligible активах держи 1 long и 1 short; при 10 — 2 long и 2 short.
5. Учти комиссии 0,10% base, 0,12% realistic, 0,20% stress и funding по фактическим timestamps. Не считать missing funding нулём.
6. Выполни заранее описанные controls, multiple-testing ledger и concentration diagnostics. Не добавляй параметры после просмотра результата и не выбирай отдельную «лучшую монету».
7. Сохрани код, тесты, per-symbol data audit, полный ledger, машинные artifacts и итоговый Markdown report. Везде маркируй вывод как `exploratory fixed-basket evidence with survivorship/selection bias`.
8. Остановись после TRAIN/VALIDATION отчёта. Не открывай HOLDOUT, не переходи к paper/live trading и не называй результат подтверждённым edge.
9. Обнови `docs/HANDOFF.md` и `docs/roadmap.md`, запусти полный test suite, закоммить и запушь изменения только в `v0/crypto-futures-analysis-88d9d19a`.

Если pre-HOLDOUT data audit не позволяет причинно построить cross-section минимум из 5 активов на достаточном периоде, выпусти `STOP` с точной причиной и не считай стратегию.
