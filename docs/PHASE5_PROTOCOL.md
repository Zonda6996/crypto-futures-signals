# Phase 5 protocol — финальная pre-TEST falsification

Статус: **зафиксирован до расчётов Phase 5**.

## Scope

- Проверяется только frozen ETHUSDT 1h-кандидат.
- Используются только TRAIN+VALIDATION 2021–2024.
- Данные с `2025-01-01 00:00:00 UTC` и позднее запрещено загружать, открывать или анализировать.
- Параметры, signal rules, calibration и стратегия не меняются.
- Основные round-trip costs: 0,10%; stress costs: 0,16%.
- Полный pre-TEST срез — descriptive falsification, а не новая OOS-оценка.
- Phase 5 является отдельным экспериментом и не смешивается с оригинальными или повторными Phase 2–4.

## Предварительно заданные диагностики

1. Temporal: календарные кварталы и полугодия; rolling 6/12/18 месяцев; longest no-profit span; maximum losing streak; recovery time.
2. Cluster: без лучших 1/3/5 календарных недель; без лучших 1/3 месяцев; без лучшего непрерывного signal-time окна 30/60/90 дней.
3. Regime: leave-one-causal-BTC-regime-out с ранее зафиксированными causal labels; режимы не используются как торговый фильтр.
4. Execution: 0,16% costs; дополнительная задержка входа на один 1h-бар; deterministic missed trades 5/10/20%; adverse entry/exit slippage; funding x2; combined stress.
5. Все сценарии сохраняются независимо от результата. Выбор лучшего сценария запрещён.

## Frozen execution stresses

- Missed-trade seeds: 5% — `5005`, 10% — `1010`, 20% — `2020`.
- Adverse slippage: 0,03% на входе и 0,03% на выходе.
- Funding stress: удвоенный funding cash flow при неизменных ценовых fills.
- Combined stress: 0,16% round-trip costs + adverse slippage 0,03% на каждой стороне + пропуск 10% сделок с seed `1010` + funding x2.
- One-bar delay использует следующий доступный 1h open и сохраняет исходный exit timestamp; сделки без допустимого положительного holding interval исключаются и учитываются в metadata.

## Неизменяемые pass/fail-критерии

Phase 5 получает PASS только если одновременно выполнены все условия:

1. Baseline положителен без top-5 сделок.
2. Baseline положителен без лучшего календарного года.
3. Baseline положителен без лучшего непрерывного 90-day signal-time кластера.
4. Frozen результат при 0,16% costs положителен.
5. Более 50% rolling 12-month окон положительны.
6. Каждый leave-one-causal-regime-out результат положителен; техническая группа `insufficient_history` не является отдельным обязательным regime-критерием.
7. Combined execution stress не отрицателен.

Критерии не меняются после просмотра результатов. Любой невыполненный пункт означает FAIL.

## Решение после Phase 5

- При FAIL текущая frozen-гипотеза останавливается; TEST остаётся закрытым.
- При PASS разрешается только подготовка отдельного immutable TEST-opening memo.
- Даже при PASS TEST не открывается без нового явного разрешения владельца.
