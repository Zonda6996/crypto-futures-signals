# План следующего чата: независимое исследование стратегии на альткоинах

## Контекст, который нельзя потерять

Репозиторий: `Zonda6996/crypto-futures-signals`.

Предыдущая гипотеза была замороженной ETHUSDT long 1h momentum-стратегией с BTC regime filter. Research commit: `81f5ea590edbc04fadce762452801c1d365470d0`. Она показала сильные результаты на pre-TEST 2021–2024 и PASS 7/7 в описательной Phase 5, но единственный заранее разрешённый TEST 2025 завершился **FAIL**:

- 32 сделки;
- expectancy `−0,160R`;
- total `−5,135R`;
- CI95 expectancy: `[−0,495R; +0,186R]`;
- max drawdown `−5,640R`.

Старый TEST уже открыт и израсходован. Его нельзя запускать повторно, использовать для настройки или выдавать новую стратегию, подобранную на 2025, за независимое подтверждение. Оригинальные Phase 2–3, дополнительные robustness-проверки, Phase 5 и TEST — разные эксперименты; результаты не смешивать.

## Цель нового исследования

Не «перенести» провалившиеся ETH-параметры на случайные монеты, а проверить новую, заранее определённую гипотезу: существует ли воспроизводимый cross-sectional или time-series momentum edge в ликвидных USD-M perpetual альткоинах после реалистичных costs, funding и ограничений исполнения.

Главный объект оценки — **единый портфель/правило по заранее определённой вселенной**, а не лучшая монета постфактум.

## Жёсткие запреты

1. Не менять, не перезапускать и не переинтерпретировать старый TEST 2025.
2. Не использовать результаты старого TEST для выбора параметров новой стратегии, кроме общего решения отказаться от старой гипотезы.
3. Не выбирать «победившие» альты по полной истории и не удалять убыточные/делистнутые инструменты задним числом.
4. Не загружать будущий holdout нового эксперимента до отдельного immutable opening memo и явного разрешения владельца.
5. Не использовать paper/live trading до независимого PASS нового holdout.

## Предлагаемый дизайн

### Фаза A — protocol и data availability audit

До расчёта доходностей зафиксировать:

- venue и тип контракта: Binance USD-M perpetual как исследовательский источник; отдельно описать переносимость на BingX;
- point-in-time universe rule, например top-N по trailing 30-day dollar volume с минимальным возрастом листинга;
- исключения только по объективным правилам: stablecoins, leveraged tokens, wrapped/duplicate exposure;
- минимальные liquidity/open-interest требования;
- правила обработки листингов, делистингов, пропусков, funding и corporate/token events;
- календарные TRAIN, VALIDATION и новый закрытый future HOLDOUT;
- costs tiers и execution assumptions;
- primary metric и pass/fail до просмотра HOLDOUT.

На этой фазе проверить, можно ли воспроизвести point-in-time universe без survivorship bias. Если нельзя — остановиться и явно снизить силу выводов.

### Фаза B — минимальная гипотеза

Сравнить малое заранее ограниченное семейство, а не широкий перебор:

1. Cross-sectional momentum: ранжирование доступных альтов по trailing return, long верхней группы и при необходимости short нижней.
2. Time-series momentum: одинаковое правило направления для каждого инструмента с portfolio volatility targeting.
3. Простые benchmark-контроли: equal-weight альты, BTC/ETH beta-matched, случайное ранжирование, delayed execution.

Заранее ограничить horizons, rebalance frequency и risk model. Все признаки должны использовать только информацию, доступную до момента решения.

### Фаза C — TRAIN/VALIDATION

- Настройка только на TRAIN.
- Один заранее выбранный вариант подтверждается на VALIDATION.
- Отчётность обязательна как по портфелю, так и по cross-section: доля положительных монет, leave-one-coin-out, leave-one-year-out, turnover, concentration top trades/coins, regime breakdown.
- Multiple-testing correction или явный учёт числа проверенных гипотез.
- Stress: удвоенные costs, дополнительная задержка, худшее исполнение внутри бара, funding perturbation, liquidity caps.

### Фаза D — pre-holdout falsification

Для единственного frozen candidate заранее зафиксировать критерии, включая:

- положительный результат после удаления top trades и top coin contributors;
- отсутствие зависимости от одного года/режима;
- положительный результат при реалистичном stress cost;
- приемлемую концентрацию и turnover;
- достаточное количество независимых rebalance periods/trades;
- стабильность небольших соседних параметров без выбора нового optimum.

### Фаза E — immutable holdout opening

Только после успешных предыдущих фаз:

- frozen commit и SHA-256 данных/артефактов;
- одна команда запуска;
- один primary metric и бинарный criterion;
- secondary diagnostics без влияния на verdict;
- one-time sentinel и audit trail;
- отдельное точное разрешение владельца.

## Предлагаемый primary metric

Для портфельной стратегии лучше заранее использовать net risk-adjusted portfolio return, например annualized Sharpe с block-bootstrap CI, а не сумму результатов отдельных монет. Точную метрику, минимальный sample size и threshold должен утвердить владелец **до** исследования и особенно до holdout.

## Первый шаг нового чата

1. Прочитать:
   - `docs/HANDOFF.md`;
   - `docs/roadmap.md`;
   - `docs/ALTCOIN_RESEARCH_NEXT_CHAT.md`;
   - `docs/TEST_OPENING_MEMO.md`;
   - `reports/private/test-opening/result.json`.
2. Подтвердить, что старый TEST не будет повторно открыт.
3. Не писать стратегию сразу: сначала подготовить `docs/ALTCOIN_PROTOCOL.md` с вариантами point-in-time universe, периодами разбиения и primary criterion.
4. Запросить у владельца выбор между cross-sectional и time-series momentum, допустимость short-позиций, размер universe и новый будущий holdout.
5. После утверждения protocol выполнять только data availability/survivorship audit; не переходить автоматически к поиску параметров.

## Ожидаемый результат первого нового этапа

Не доходность и не «лучшая монета», а утверждённый protocol плюс доказательство, что данные позволяют построить point-in-time universe без утечки будущего и survivorship bias.
