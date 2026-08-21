# ALT-XSMOM-001-B — read-only post-mortem

**Статус:** Фаза 1 завершена; исходный verdict остаётся **FAIL / STOP**.  
**Evidence:** exploratory fixed-basket evidence with survivorship/selection bias.  
**Данные:** только существующие TRAIN/VALIDATION ledgers, строго до `2026-01-01T00:00:00Z`; HOLDOUT остаётся **SEALED**.

## Что было проверено

Диагностика воспроизводится командой `python3 -m research.altcoin_basket_postmortem`. Скрипт сначала проверяет timestamps, затем разлагает frozen primary `30d / 24h` при realistic round-trip cost `0.12%`. Parameter search, изменение basket и новые backtests не выполнялись. Итоги сверены с `validation-result.json`.

## Механика результата

| Split | Gross sum | Funding sum | Cost drag | Net arithmetic sum |
|---|---:|---:|---:|---:|
| TRAIN | +3.2661 | +0.0383 | −1.7292 | +1.5752 |
| VALIDATION | +0.3563 | +0.0070 | −0.7440 | **−0.3808** |

На VALIDATION наблюдаемый gross effect был положительным, но более чем полностью поглощён фиксированной стоимостью ежедневного полного round trip. Turnover равен `1.0` в каждом из 620 active periods. Funding был небольшим положительным вкладом и не объясняет FAIL; missing funding observations в active ledger отсутствуют.

## Long/short legs

| VALIDATION leg | Gross | Funding | Cost | Net |
|---|---:|---:|---:|---:|
| Long | +0.4726 | −0.0279 | −0.3720 | **+0.0727** |
| Short | −0.1163 | +0.0349 | −0.3720 | **−0.4534** |

Главный механический источник VALIDATION FAIL — short leg: он был отрицателен уже gross и после costs дал `−0.4534`. Long leg сохранил лишь небольшой положительный net вклад. Это описание просмотренного результата, а не разрешение отключить short leg или подобрать новый вариант.

## Symbols и концентрация

Крупнейшие положительные net arithmetic contributions: `XRPUSDT +0.2932`, `ADAUSDT +0.1756`, `DOGEUSDT +0.1610`. Крупнейшие отрицательные: `LTCUSDT −0.2968`, `BNBUSDT −0.2839`, `LINKUSDT −0.2626`. Вклад нестабилен между активами и не подтверждает universe-level edge.

Frozen per-position concentration limit `25%` нарушался в `620/620` VALIDATION periods и `1441/1441` TRAIN periods: inverse-vol weighting внутри двух активов на сторону систематически создавал хотя бы одну позицию выше лимита. Исходный attribution test также показал чрезмерную зависимость от отдельных symbols.

## Нейтральные календарные срезы VALIDATION

| Quarter | Net arithmetic sum |
|---|---:|
| 2024-Q2 | −0.1329 |
| 2024-Q3 | −0.1625 |
| 2024-Q4 | +0.3343 |
| 2025-Q1 | −0.2019 |
| 2025-Q2 | −0.0827 |
| 2025-Q3 | −0.0167 |
| 2025-Q4 | −0.1184 |

Только один из семи календарных кварталов положителен после costs. Эти срезы являются описательной диагностикой market regimes; выбирать по ним режим или фильтр запрещено.

## Вывод

FAIL объясняется сочетанием трёх наблюдаемых механизмов: cost drag превышает весь VALIDATION gross effect, short leg отрицателен до costs, а позиции систематически нарушают concentration limit. Результат также неустойчив по symbols и календарю. Это не создаёт автоматически новую стратегию: конкретные изменения turnover, short construction, weighting или universe сейчас не тестировались и не разрешены.

## Governance и следующий gate

Фаза 1 завершена. Работа останавливается перед новой гипотезой. Только отдельное решение владельца может открыть Фазу 2 с новым protocol ID, заранее заданными правилами и новым будущим sealed HOLDOUT. Retuning `ALT-XSMOM-001-B`, повторный выбор grid point, открытие текущего HOLDOUT и paper/live trading запрещены.

Machine-readable artifacts: `reports/altcoin-phase-b/diagnostics/postmortem.json`, `symbol-attribution-train.csv`, `symbol-attribution-validation.csv`.
