# TIDAL Research

Исследовательский движок крипто-фьючерсных стратегий с предрегистрационными
протоколами: правила фиксируются ДО анализа, гейты не ослабляются никогда,
каждый прогон оставляет артефакты с SHA-256.

## Живая стратегия

**carry-select** — сбор фандинга на 10 USDT-M перпах: шорт топ-3 платильщиков /
лонг дно-3, ежедневная пересборка, ATR-стопы, фулл-тейк 1:1, инверсно-волатильные
веса, BTC-хедж. Единственная конфигурация программы, прошедшая весь стек гейтов
(SPA, DSR, Holm, bootstrap, стресс, темпоральная консистентность).

Простыми словами: `docs/STRATEGIES/carry-select.md`.

## Быстрый старт

```bash
uv sync --frozen --group dev
uv run python -m pytest
uv run python -m research.altcoin_carry_forward --run      # день форварда
uv run python -m research.altcoin_carry_forward --status   # состояние книги
```

## Структура

```
AGENTS.md            правила работы (точка входа для ИИ и людей)
docs/HANDOFF.md      текущее состояние
docs/ROADMAP.md      очередь работ
docs/NEGATIVE-KNOWLEDGE.md   всё отвергнутое — не переоткрывать
docs/STRATEGIES/     живые стратегии простым языком
docs/ALTCOIN_*_FROZEN_PROTOCOL.md   замороженные протоколы прогонов (не двигать)
docs/archive/        исторические handoff'ы
research/            детерминированные движки прогонов и форвард-раннер
reports/artifacts/   артефакты каждого прогона (коммитятся)
tests/               137 тестов
```

Данные: `D:\alt-multitf-005-data\inputs\merged` (единственное, что читают движки).
