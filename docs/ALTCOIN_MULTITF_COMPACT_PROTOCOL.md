# ALT-MULTITF-004 — compact liquidity baseline

Статус: **DATA PHASE DONE / STOP перед Phase 2**
Дата freeze: 22 августа 2026 года  
Рынок: Binance USD-M linear USDT perpetual futures

## Причина нового protocol ID

`ALT-MULTITF-003` не изменяется задним числом. Его незакоммиченные Phase 1A payload, полный manifest, acquisition plan и roster snapshot были утрачены вместе с прежним sandbox, поэтому побитовое продолжение невозможно. Исторические цифры Phase 1A остаются в отчёте как факты того запуска, но не считаются восстановленным input текущей работы.

## Frozen universe

До загрузки market history сохраняются raw official responses Binance USD-M `exchangeInfo` и `ticker/24hr`, timestamps и SHA-256. Среди контрактов `TRADING`, `PERPETUAL`, `quoteAsset=USDT`, `marginAsset=USDT`, кроме `BTCUSDT` и `ETHUSDT`, выбираются ровно первые 40 по числовому текущему `quoteVolume`; tie-break — symbol по возрастанию. Полный candidate ranking сохраняется. После snapshot roster нельзя менять по coverage, возрасту, будущей ликвидности или результатам.

Это намеренно компактный current-liquidity universe с survivorship и current-selection bias. Результаты относятся только к замороженному roster и не оценивают все исторические Binance contracts.

## Data phase

Development: `[2020-01-01T00:00:00Z, 2026-01-01T00:00:00Z)`. Источники — только официальные monthly Binance Vision USD-M `5m` klines и funding-rate archives. Higher-timeframe archives не скачиваются.

В этой работе holdout отсутствует физически: его нельзя планировать, скачивать, перечислять, читать или оценивать. Новый prospective holdout и его календарь разрешается определить только отдельным будущим owner decision до соответствующих данных.

Data phase включает только acquisition, checksum inventory, normalization, quality audit, causal eligibility и построение `15m`, `30m`, `1h`, `2h`, `4h`, `1d` из полных закрытых `5m` bars. Signals, strategy ranking, portfolio construction, PnL, backtest и grid search запрещены.

## Validation и causal availability

Обязательны schema, finite numeric values, UTC millisecond timestamps, strict ordering, byte-equivalent duplicate removal, conflict fail-closed, OHLC consistency и boundaries. Gap длиннее `30m` исключает только затронутые decisions до восстановления clean trailing window. Неполный higher-TF bucket не публикуется; bar становится доступен только после close последнего входящего `5m` bar.

На каждом decision timestamp eligibility требует возраст от первого observation `>=30d`, trailing `30d` coverage `>=99%`, отсутствие gap `>30m` в clean trailing window и median causal daily quote volume за 30 полных UTC-дней. Cohorts: `$10m–25m` и `>=25m`; всё ниже — ineligible. Недостаточная история не удаляет symbol из frozen roster.

## Governance

Data phase DONE только после полного raw и normalized manifests, SHA-256 filesystem verification, exact audit inventory и focused tests. Raw/normalized payload не коммитятся. Phase 2 не начинается автоматически и требует отдельного approval.
