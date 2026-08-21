"""Frozen causal engine for ALT-LOMOM-002-A (TRAIN only)."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from math import sqrt
from statistics import pstdev
from typing import Sequence

from .altcoin_basket_data import BASKET, DAY_MS, HOUR_MS, MIN_COVERAGE, MIN_CROSS_SECTION, BasketBar, FundingEvent, assert_pre_holdout
from .altcoin_basket_engine import SymbolSeries

PROTOCOL_ID = "ALT-LOMOM-002-A"
EVIDENCE_LABEL = "exploratory fixed-basket evidence with survivorship/selection bias"
MOMENTUM_DAYS = 30
TOP_K = 4
BASE_WEIGHT = 0.25
REBALANCE_DAYS = 7
REBALANCE_WEEKDAY = 0  # Monday
REBALANCE_HOUR_UTC = 0
VOL_WINDOW_DAYS = 30
VOL_TARGET = 0.20
ANNUAL_DAYS = 365
BOOTSTRAP_BLOCK_DAYS = 30
REALISTIC_COST = 0.0012
STRESS_COST = 0.0020
PARTICIPATION_RATE = 0.01
INITIAL_CAPITAL_QUOTE = 1.0


@dataclass(frozen=True)
class Holding:
    symbol: str
    weight: float
    momentum: float
    participation_cap: float


@dataclass(frozen=True)
class DayRecord:
    day_ms: int
    decision_ms: int | None
    holdings: tuple[Holding, ...]
    multiplier: float
    gross_return: float
    funding_return: float
    turnover: float
    net_realistic: float
    net_stress: float
    equity_realistic: float
    equity_stress: float
    status: str
    violations: tuple[str, ...]


def weekly_decisions(start_ms: int, end_ms: int) -> list[int]:
    assert_pre_holdout(start_ms, end_ms - 1)
    day = start_ms - start_ms % DAY_MS
    out: list[int] = []
    while day < end_ms:
        dt = datetime.fromtimestamp(day / 1000, tz=timezone.utc)
        if dt.weekday() == REBALANCE_WEEKDAY and dt.hour == REBALANCE_HOUR_UTC and day >= start_ms:
            out.append(day)
        day += DAY_MS
    return out


def causal_rank(series: dict[str, SymbolSeries], decision_ms: int) -> list[tuple[str, float]]:
    assert_pre_holdout(decision_ms)
    canonical = {symbol: i for i, symbol in enumerate(BASKET)}
    scored: list[tuple[str, float]] = []
    for symbol in BASKET:
        item = series.get(symbol)
        if item is None or not item.has_listing_age(decision_ms) or item.trailing_coverage(decision_ms) < MIN_COVERAGE:
            continue
        momentum = item.momentum(decision_ms, MOMENTUM_DAYS)
        if momentum is not None:
            scored.append((symbol, momentum))
    scored.sort(key=lambda row: (-row[1], canonical[row[0]]))
    return scored


def daily_return(item: SymbolSeries, start_ms: int, end_ms: int) -> tuple[float, float] | None:
    entry = item.execution_bar(start_ms)
    exit_bar = item.execution_bar(end_ms)
    if entry is None or exit_bar is None or entry.ts != start_ms or exit_bar.ts != end_ms or entry.open <= 0:
        return None
    funding, observed = item.funding_between(start_ms, end_ms)
    if observed < item.funding_expected_count(start_ms, end_ms):
        return None
    return exit_bar.open / entry.open - 1.0, -funding


def shadow_daily_returns(series: dict[str, SymbolSeries], symbols: Sequence[str], decision_ms: int) -> list[float] | None:
    values: list[float] = []
    for offset in range(VOL_WINDOW_DAYS, 0, -1):
        start = decision_ms - offset * DAY_MS
        end = start + DAY_MS
        parts = [daily_return(series[symbol], start, end) for symbol in symbols]
        if any(part is None for part in parts):
            return None
        values.append(sum(BASE_WEIGHT * (part[0] + part[1]) for part in parts if part is not None))
    return values


def volatility_multiplier(daily_returns: Sequence[float]) -> float:
    if len(daily_returns) != VOL_WINDOW_DAYS:
        return 0.0
    sigma = pstdev(daily_returns) * sqrt(ANNUAL_DAYS)
    if sigma <= 0:
        return 0.0
    return min(1.0, max(0.0, VOL_TARGET / sigma))


def participation_cap(item: SymbolSeries, decision_ms: int, equity_quote: float) -> float:
    left = decision_ms - HOUR_MS
    idx = item.closed_index(decision_ms)
    if idx <= 0 or item.bars[idx - 1].ts != left or equity_quote <= 0:
        return 0.0
    return PARTICIPATION_RATE * item.bars[idx - 1].quote_volume / equity_quote


def target_holdings(series: dict[str, SymbolSeries], decision_ms: int, equity_quote: float) -> tuple[tuple[Holding, ...], float, str]:
    ranked = causal_rank(series, decision_ms)
    if len(ranked) < MIN_CROSS_SECTION:
        return (), 0.0, "eligible_below_5"
    selected = ranked[:TOP_K]
    shadow = shadow_daily_returns(series, [symbol for symbol, _ in selected], decision_ms)
    if shadow is None:
        return (), 0.0, "volatility_warmup_or_missing_data"
    multiplier = volatility_multiplier(shadow)
    holdings = []
    for symbol, momentum in selected:
        cap = participation_cap(series[symbol], decision_ms, equity_quote)
        holdings.append(Holding(symbol, min(BASE_WEIGHT * multiplier, cap), momentum, cap))
    return tuple(holdings), multiplier, "active" if holdings else "cash"


def turnover(old: Sequence[Holding], new: Sequence[Holding]) -> float:
    before = {x.symbol: x.weight for x in old}
    after = {x.symbol: x.weight for x in new}
    return sum(abs(after.get(symbol, 0.0) - before.get(symbol, 0.0)) for symbol in set(before) | set(after))


def constraint_violations(holdings: Sequence[Holding], decision_ms: int, day_ms: int) -> tuple[str, ...]:
    errors: list[str] = []
    if day_ms >= 1767225600000 or decision_ms >= 1767225600000:
        errors.append("data_boundary")
    if any(x.weight < 0 for x in holdings): errors.append("short_exposure")
    if any(x.weight > BASE_WEIGHT + 1e-12 for x in holdings): errors.append("per_symbol")
    if sum(x.weight for x in holdings) > 1.0 + 1e-12: errors.append("gross_exposure")
    if any(x.weight > x.participation_cap + 1e-12 for x in holdings): errors.append("participation")
    return tuple(errors)


def run_train(series: dict[str, SymbolSeries], start_ms: int, end_ms: int) -> list[DayRecord]:
    assert_pre_holdout(start_ms, end_ms - 1)
    decisions = set(weekly_decisions(start_ms, end_ms))
    holdings: tuple[Holding, ...] = ()
    multiplier = 0.0
    last_decision: int | None = None
    eq_real = eq_stress = INITIAL_CAPITAL_QUOTE
    records: list[DayRecord] = []
    day = start_ms - start_ms % DAY_MS
    while day + DAY_MS < end_ms:
        turn = 0.0
        status = "hold"
        if day in decisions:
            new, multiplier, status = target_holdings(series, day, eq_real)
            turn = turnover(holdings, new)
            holdings, last_decision = new, day
        components = [(h, daily_return(series[h.symbol], day, day + DAY_MS)) for h in holdings]
        if any(value is None for _, value in components):
            gross = funding = 0.0
            status = "missing_required_observation_cash"
            turn += sum(h.weight for h in holdings)
            holdings = ()
        else:
            gross = sum(h.weight * value[0] for h, value in components if value is not None)
            funding = sum(h.weight * value[1] for h, value in components if value is not None)
        net_real = gross + funding - turn * REALISTIC_COST
        net_stress = gross + funding - turn * STRESS_COST
        eq_real *= 1.0 + net_real
        eq_stress *= 1.0 + net_stress
        violations = constraint_violations(holdings, last_decision or day, day)
        records.append(DayRecord(day, last_decision if day in decisions else None, holdings, multiplier, gross, funding, turn, net_real, net_stress, eq_real, eq_stress, status, violations))
        day += DAY_MS
    return records


def summary(records: Sequence[DayRecord], stress: bool = False) -> dict:
    values = [r.net_stress if stress else r.net_realistic for r in records]
    equity = [r.equity_stress if stress else r.equity_realistic for r in records]
    sigma = pstdev(values) if values else 0.0
    mean = sum(values) / len(values) if values else 0.0
    peak = 1.0; max_dd = 0.0
    for value in equity:
        peak = max(peak, value); max_dd = min(max_dd, value / peak - 1.0)
    return {"daily_equivalent_observations": len(values), "scheduled_rebalances": sum(r.decision_ms is not None for r in records), "net_sharpe": mean / sigma * sqrt(ANNUAL_DAYS) if sigma else None, "compounded_net_return": equity[-1] - 1.0 if equity else 0.0, "max_drawdown": max_dd, "turnover_sum": sum(r.turnover for r in records), "gross_return_sum": sum(r.gross_return for r in records), "funding_return_sum": sum(r.funding_return for r in records), "cost_drag": sum(r.turnover for r in records) * (STRESS_COST if stress else REALISTIC_COST), "violation_count": sum(len(r.violations) for r in records)}


def block_bootstrap(records: Sequence[DayRecord], iterations: int = 2000, seed: int = 20260821) -> dict:
    values = [r.net_realistic for r in records]
    if len(values) < BOOTSTRAP_BLOCK_DAYS: return {"iterations": 0, "ci95_low": None, "ci95_high": None, "block_length_days": BOOTSTRAP_BLOCK_DAYS}
    rng = random.Random(seed); samples = []
    for _ in range(iterations):
        drawn = []
        while len(drawn) < len(values):
            start = rng.randrange(len(values))
            drawn.extend(values[(start+i) % len(values)] for i in range(BOOTSTRAP_BLOCK_DAYS))
        drawn = drawn[:len(values)]; sigma = pstdev(drawn)
        if sigma: samples.append(sum(drawn)/len(drawn)/sigma*sqrt(ANNUAL_DAYS))
    samples.sort()
    return {"iterations": len(samples), "ci95_low": samples[int(.025*len(samples))], "ci95_high": samples[min(len(samples)-1, int(.975*len(samples)))], "block_length_days": BOOTSTRAP_BLOCK_DAYS}
