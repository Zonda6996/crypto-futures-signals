# ALT-XSMOM-001-B — frozen TRAIN/VALIDATION result

**Дата выполнения:** 21 августа 2026 года  
**Маркировка:** **exploratory fixed-basket evidence with survivorship/selection bias**  
**Verdict:** **FAIL / STOP** — frozen primary не прошёл VALIDATION gate. HOLDOUT не открывался.

## Governance

Исследование выполнено только на неизменяемой корзине `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`, `ADAUSDT`, `DOGEUSDT`, `LINKUSDT`, `LTCUSDT`, `AVAXUSDT`, `DOTUSDT`. Данные и вычисления строго ограничены timestamps `< 2026-01-01T00:00:00Z`. Результат не отменяет строгий Phase A `STOP`, не доказывает universe-level edge и не разрешает paper/live trading.

## Pre-HOLDOUT data audit

Все 10 серий заканчиваются `2025-12-31T23:00:00Z`; HOLDOUT rows, дубли, off-grid timestamps, невалидные OHLC и отрицательные quote volumes отсутствуют. Семь price-серий имеют coverage `100%`; у `LTCUSDT`, `SOLUSDT` и `XRPUSDT` по 120 отсутствующих hourly bars, full-span coverage соответственно `99.771%`, `99.742%` и `99.771%`. Funding загружен для всех активов; фактическая period-level проверка не трактует отсутствие funding как ноль. Максимум одновременно eligible активов равен 10, поэтому gate `>=5` пройден.

Машинные детали: `reports/altcoin-phase-b/per-symbol-audit.json`, `eligibility-timeline.json`, `gate.json`, manifests и `input-hashes.json`.

## Frozen calendar

Границы получены только из coverage-календаря до расчёта returns:

- TRAIN: `[2020-05-05T00:00:00Z, 2024-04-20T00:00:00Z)` — 1446 дней;
- VALIDATION: `[2024-04-20T00:00:00Z, 2026-01-01T00:00:00Z)` — 621 день;
- HOLDOUT: `[2026-01-01T00:00:00Z, +∞)` — **SEALED**.

## TRAIN selection

Все 9 заранее заданных комбинаций horizons `7/14/30d` × rebalance `8/12/24h` записаны в `train-grid.json`. По frozen TRAIN-only metric — net annualised Sharpe при realistic round-trip cost `0.12%` — выбран единственный primary: **30d momentum / 24h rebalance**.

TRAIN primary при `0.12%`: 1441 active periods, net Sharpe `0.7530`, compounded net return `+182.19%`, max drawdown `−55.59%`. При stress `0.20%` compounded result уже `−10.90%`.

## One-time VALIDATION result

Primary был подтверждён один раз без переотбора параметров:

| Cost | Net Sharpe | Compounded net return | Max drawdown |
|---|---:|---:|---:|
| 0.10% | −0.5509 | −27.44% | −42.66% |
| 0.12% | **−0.8170** | **−35.90%** | **−46.78%** |
| 0.20% | −1.8813 | −60.99% | −62.68% |

VALIDATION содержит 620 active daily periods и 620 independent rebalance decisions. Stationary/block-bootstrap 95% CI для Sharpe при `0.12%`: **[−2.4489; +0.6316]** (2000 iterations, frozen 14-day block). Lower bound не выше нуля, point estimate ниже `0.75`, stress result отрицателен. Следовательно, mandatory advancement rule не выполнен.

Gross return sum до costs был `+0.3563`, funding sum `+0.0070`, но cost drag при `0.12%` составил `0.7440`: наблюдавшийся gross effect не пережил execution costs. Zero-cost reference был положительным (Sharpe `0.7795`, compounded `+34.90%`), что подчёркивает cost sensitivity, а не подтверждённый tradable edge.

## Controls and concentration

- one-bar delayed execution: Sharpe `−0.8509`, compounded `−36.75%`;
- sign-flipped ranking: Sharpe `−2.3759`, compounded `−69.04%`;
- максимальная положительная per-symbol contribution относительно абсолютного net sum: `77.0%` (`XRPUSDT`), выше лимита `25%`;
- 2025 создал отрицательный net sum `−0.4197`; результат не является устойчивым по календарю.

Поскольку primary уже однозначно провалил обязательный VALIDATION gate, отрицательный verdict не меняется никакими secondary diagnostics. Нельзя выбирать другую grid point, отдельную монету или новый параметр после просмотра результата.

## Ledgers and artifacts

- полный leg-level TRAIN ledger: `reports/altcoin-phase-b/ledger-train.csv`;
- полный leg-level VALIDATION ledger: `reports/altcoin-phase-b/ledger-validation.csv`;
- полный multiple-testing ledger 9 frozen TRAIN configurations: `reports/altcoin-phase-b/train-grid.json`;
- frozen primary: `primary-selection.json`;
- VALIDATION, bootstrap, attribution и controls: `validation-result.json`;
- frozen calendar: `splits.json`.

## Final decision

**FAIL / STOP.** Frozen 30d/24h primary показал отрицательный net Sharpe и отрицательную compounded доходность на VALIDATION при всех трёх заранее заданных cost scenarios; bootstrap CI пересекает ноль, stress отрицателен, concentration rule нарушен. Исследование останавливается после TRAIN/VALIDATION. HOLDOUT остаётся закрытым; retuning этой версии, замена состава basket, повторный выбор по VALIDATION и переход к paper/live trading запрещены.
