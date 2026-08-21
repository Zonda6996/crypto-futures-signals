"""Causal cross-sectional long/short momentum engine for ALT-XSMOM-001-B.

Exploratory fixed-basket evidence with survivorship/selection bias.

Causality rules enforced here:

* A decision at timestamp `t` may only read bars with `open_time + 1h <= t`,
  i.e. bars that have fully closed before `t`.
* Positions opened at `t` are executed at the open of the first bar whose open
  time is `>= t` (next-bar execution) and closed at the open of the first bar at
  or after the following rebalance.
* Funding is charged at the actual funding timestamps inside the holding
  interval, on the actual side. Missing funding is never treated as zero: the
  affected leg is excluded from the cross-section for that period.
* Eligibility requires 90 days of the contract's own history plus >=95% hourly
  coverage over the trailing 30 days, evaluated strictly before the decision.
"""

from __future__ import annotations

import random
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from math import sqrt
from statistics import median, pstdev
from typing import Sequence

from .altcoin_basket_data import (
    BASKET,
    COVERAGE_WINDOW_MS,
    DAY_MS,
    HOUR_MS,
    MIN_COVERAGE,
    MIN_CROSS_SECTION,
    MIN_LISTING_AGE_MS,
    BasketBar,
    FundingEvent,
    assert_pre_holdout,
)

#: Preregistered grid. Never extend after seeing results.
RANKING_HORIZONS_DAYS: tuple[int, ...] = (7, 14, 30)
REBALANCE_HOURS: tuple[int, ...] = (8, 12, 24)

#: Cost scenarios as round-trip fractions of notional.
COST_SCENARIOS: dict[str, float] = {
    "base_0_10pct": 0.0010,
    "realistic_0_12pct": 0.0012,
    "stress_0_20pct": 0.0020,
}

VOLATILITY_WINDOW_MS = 30 * DAY_MS
WINSOR_QUANTILE = 0.10
GROSS_EXPOSURE = 1.0


@dataclass(frozen=True)
class SymbolSeries:
    """Immutable per-symbol view with sorted timestamps for causal lookups."""

    symbol: str
    bars: tuple[BasketBar, ...]
    funding: tuple[FundingEvent, ...]
    timestamps: tuple[int, ...] = field(default=())
    funding_ts: tuple[int, ...] = field(default=())

    @staticmethod
    def build(symbol: str, bars: Sequence[BasketBar], funding: Sequence[FundingEvent]) -> "SymbolSeries":
        ordered = tuple(sorted(bars, key=lambda bar: bar.ts))
        ordered_funding = tuple(sorted(funding, key=lambda event: event.ts))
        return SymbolSeries(
            symbol=symbol,
            bars=ordered,
            funding=ordered_funding,
            timestamps=tuple(bar.ts for bar in ordered),
            funding_ts=tuple(event.ts for event in ordered_funding),
        )

    def closed_index(self, decision_ms: int) -> int:
        """Index one past the last bar that has fully closed before `decision_ms`."""
        return bisect_right(self.timestamps, decision_ms - HOUR_MS)

    def close_at_or_before(self, decision_ms: int) -> tuple[int, float] | None:
        idx = self.closed_index(decision_ms)
        if idx <= 0:
            return None
        bar = self.bars[idx - 1]
        return bar.ts, bar.close

    def execution_bar(self, decision_ms: int) -> BasketBar | None:
        """First bar whose open time is at or after the decision timestamp."""
        idx = bisect_left(self.timestamps, decision_ms)
        if idx >= len(self.bars):
            return None
        return self.bars[idx]

    def trailing_coverage(self, decision_ms: int) -> float:
        window_start = decision_ms - COVERAGE_WINDOW_MS
        left = bisect_left(self.timestamps, window_start)
        right = bisect_right(self.timestamps, decision_ms - HOUR_MS)
        return (right - left) / (COVERAGE_WINDOW_MS // HOUR_MS)

    def has_listing_age(self, decision_ms: int) -> bool:
        if not self.timestamps:
            return False
        return decision_ms - self.timestamps[0] >= MIN_LISTING_AGE_MS

    def momentum(self, decision_ms: int, horizon_days: int) -> float | None:
        """Trailing return over `horizon_days`, using only closed bars."""
        end = self.close_at_or_before(decision_ms)
        if end is None:
            return None
        end_ts, end_close = end
        start = self.close_at_or_before(decision_ms - horizon_days * DAY_MS)
        if start is None:
            return None
        start_ts, start_close = start
        if start_close <= 0 or start_ts >= end_ts:
            return None
        return end_close / start_close - 1

    def realised_volatility(self, decision_ms: int) -> float | None:
        """Trailing 30-day hourly realised volatility from closed bars only."""
        right = bisect_right(self.timestamps, decision_ms - HOUR_MS)
        left = bisect_left(self.timestamps, decision_ms - VOLATILITY_WINDOW_MS)
        window = self.bars[left:right]
        if len(window) < 24 * 7:
            return None
        returns = [
            window[i].close / window[i - 1].close - 1
            for i in range(1, len(window))
            if window[i - 1].close > 0
        ]
        if len(returns) < 24 * 7:
            return None
        sigma = pstdev(returns)
        return sigma if sigma > 0 else None

    def funding_between(self, start_ms: int, end_ms: int) -> tuple[float, int]:
        """Sum funding rates in [start_ms, end_ms) with the event count."""
        left = bisect_left(self.funding_ts, start_ms)
        right = bisect_left(self.funding_ts, end_ms)
        events = self.funding[left:right]
        return sum(event.rate for event in events), len(events)

    def funding_expected_count(self, start_ms: int, end_ms: int) -> int:
        """Binance USD-M funding settles every 8 hours."""
        if end_ms <= start_ms:
            return 0
        return max(1, round((end_ms - start_ms) / (8 * HOUR_MS)))


@dataclass(frozen=True)
class Leg:
    symbol: str
    side: int
    weight: float
    entry_ts: int
    exit_ts: int
    entry_price: float
    exit_price: float
    gross_return: float
    funding_return: float
    momentum: float
    volatility: float


@dataclass(frozen=True)
class RebalancePeriod:
    decision_ms: int
    entry_ms: int
    exit_ms: int
    eligible: tuple[str, ...]
    legs: tuple[Leg, ...]
    gross_return: float
    funding_return: float
    skipped_reason: str | None = None

    def net_return(self, cost_round_trip: float) -> float:
        turnover = sum(abs(leg.weight) for leg in self.legs)
        return self.gross_return + self.funding_return - turnover * cost_round_trip


def eligible_symbols(series: dict[str, SymbolSeries], decision_ms: int) -> tuple[list[str], dict[str, str]]:
    """Deterministic eligibility in canonical basket order; absent names are never substituted."""
    assert_pre_holdout(decision_ms)
    eligible: list[str] = []
    reasons: dict[str, str] = {}
    for symbol in BASKET:
        item = series.get(symbol)
        if item is None or not item.timestamps:
            reasons[symbol] = "no_data"
            continue
        if not item.has_listing_age(decision_ms):
            reasons[symbol] = "listing_age_below_90d"
            continue
        coverage = item.trailing_coverage(decision_ms)
        if coverage < MIN_COVERAGE:
            reasons[symbol] = "trailing_coverage_below_95pct"
            continue
        eligible.append(symbol)
    return eligible, reasons


def book_size(eligible_count: int) -> int:
    """Frozen sizing: 1 per side for 5-9 eligible, 2 per side for 10."""
    if eligible_count >= 10:
        return 2
    if eligible_count >= MIN_CROSS_SECTION:
        return 1
    return 0


def winsorised_inverse_vol_weights(
    values: dict[str, float],
    *,
    quantile: float = WINSOR_QUANTILE,
) -> dict[str, float]:
    """Causal cross-sectional winsorisation of volatility, then inverse-vol weights."""
    if not values:
        return {}
    ordered = sorted(values.values())
    lo_index = max(0, int(len(ordered) * quantile) - 1)
    hi_index = min(len(ordered) - 1, int(len(ordered) * (1 - quantile)))
    low, high = ordered[lo_index], ordered[hi_index]
    clipped = {symbol: min(max(value, low), high) for symbol, value in values.items()}
    inverse = {symbol: 1.0 / value for symbol, value in clipped.items() if value > 0}
    total = sum(inverse.values())
    if total <= 0:
        return {}
    return {symbol: value / total for symbol, value in inverse.items()}


def rank_symbols(
    series: dict[str, SymbolSeries],
    eligible: Sequence[str],
    decision_ms: int,
    horizon_days: int,
) -> list[tuple[str, float]]:
    """Rank by trailing momentum; ties resolved by canonical basket order."""
    scored: list[tuple[str, float]] = []
    for symbol in eligible:
        value = series[symbol].momentum(decision_ms, horizon_days)
        if value is None:
            continue
        scored.append((symbol, value))
    canonical = {symbol: index for index, symbol in enumerate(BASKET)}
    scored.sort(key=lambda item: (-item[1], canonical[item[0]]))
    return scored


def build_period(
    series: dict[str, SymbolSeries],
    decision_ms: int,
    next_decision_ms: int,
    horizon_days: int,
    *,
    ranker=rank_symbols,
) -> RebalancePeriod:
    """Construct one long/short rebalance period with strictly causal inputs."""
    assert_pre_holdout(decision_ms, next_decision_ms - 1)
    eligible, _ = eligible_symbols(series, decision_ms)
    if len(eligible) < MIN_CROSS_SECTION:
        return RebalancePeriod(
            decision_ms, decision_ms, next_decision_ms, tuple(eligible), (), 0.0, 0.0,
            skipped_reason="cross_section_below_5",
        )

    size = book_size(len(eligible))
    scored = ranker(series, eligible, decision_ms, horizon_days)
    if len(scored) < 2 * size:
        return RebalancePeriod(
            decision_ms, decision_ms, next_decision_ms, tuple(eligible), (), 0.0, 0.0,
            skipped_reason="insufficient_ranked_symbols",
        )

    longs = [symbol for symbol, _ in scored[:size]]
    shorts = [symbol for symbol, _ in scored[-size:]]
    if set(longs) & set(shorts):
        return RebalancePeriod(
            decision_ms, decision_ms, next_decision_ms, tuple(eligible), (), 0.0, 0.0,
            skipped_reason="overlapping_books",
        )

    selected = longs + shorts
    volatility: dict[str, float] = {}
    for symbol in selected:
        sigma = series[symbol].realised_volatility(decision_ms)
        if sigma is None:
            return RebalancePeriod(
                decision_ms, decision_ms, next_decision_ms, tuple(eligible), (), 0.0, 0.0,
                skipped_reason="missing_volatility",
            )
        volatility[symbol] = sigma

    long_weights = winsorised_inverse_vol_weights({s: volatility[s] for s in longs})
    short_weights = winsorised_inverse_vol_weights({s: volatility[s] for s in shorts})
    if not long_weights or not short_weights:
        return RebalancePeriod(
            decision_ms, decision_ms, next_decision_ms, tuple(eligible), (), 0.0, 0.0,
            skipped_reason="missing_weights",
        )

    legs: list[Leg] = []
    momentum_by_symbol = dict(scored)
    for symbol, side, weights in (
        *[(s, 1, long_weights) for s in longs],
        *[(s, -1, short_weights) for s in shorts],
    ):
        item = series[symbol]
        entry_bar = item.execution_bar(decision_ms)
        exit_bar = item.execution_bar(next_decision_ms)
        if entry_bar is None or exit_bar is None or entry_bar.ts >= exit_bar.ts:
            return RebalancePeriod(
                decision_ms, decision_ms, next_decision_ms, tuple(eligible), (), 0.0, 0.0,
                skipped_reason="missing_execution_bar",
            )
        rate_sum, observed = item.funding_between(entry_bar.ts, exit_bar.ts)
        expected = item.funding_expected_count(entry_bar.ts, exit_bar.ts)
        if observed < expected:
            # Missing funding is not zero: drop the whole cross-section period.
            return RebalancePeriod(
                decision_ms, decision_ms, next_decision_ms, tuple(eligible), (), 0.0, 0.0,
                skipped_reason="missing_funding",
            )
        # Open-to-open: entry and exit both execute at bar opens, never at a signal close.
        gross = side * (exit_bar.open / entry_bar.open - 1)
        weight = weights[symbol] * GROSS_EXPOSURE / 2.0
        legs.append(
            Leg(
                symbol=symbol,
                side=side,
                weight=weight,
                entry_ts=entry_bar.ts,
                exit_ts=exit_bar.ts,
                entry_price=entry_bar.open,
                exit_price=exit_bar.open,
                gross_return=gross,
                funding_return=-side * rate_sum,
                momentum=momentum_by_symbol.get(symbol, 0.0),
                volatility=volatility[symbol],
            )
        )

    gross_total = sum(leg.weight * leg.gross_return for leg in legs)
    funding_total = sum(leg.weight * leg.funding_return for leg in legs)
    entry_ms = min(leg.entry_ts for leg in legs)
    exit_ms = max(leg.exit_ts for leg in legs)
    return RebalancePeriod(
        decision_ms, entry_ms, exit_ms, tuple(eligible), tuple(legs), gross_total, funding_total
    )


def decision_timestamps(start_ms: int, end_ms: int, rebalance_hours: int) -> list[int]:
    """Rebalance grid aligned to the UTC hour, strictly inside the pre-HOLDOUT window."""
    step = rebalance_hours * HOUR_MS
    first = start_ms + (-start_ms % step)
    stamps = []
    current = first
    while current < end_ms:
        stamps.append(current)
        current += step
    return stamps


def run_configuration(
    series: dict[str, SymbolSeries],
    start_ms: int,
    end_ms: int,
    horizon_days: int,
    rebalance_hours: int,
    *,
    ranker=rank_symbols,
    execution_delay_bars: int = 0,
) -> list[RebalancePeriod]:
    """Run one grid point. `execution_delay_bars` supports the delayed-execution control."""
    stamps = decision_timestamps(start_ms, end_ms, rebalance_hours)
    periods: list[RebalancePeriod] = []
    for index, decision_ms in enumerate(stamps[:-1]):
        entry_decision = decision_ms + execution_delay_bars * HOUR_MS
        next_decision = stamps[index + 1] + execution_delay_bars * HOUR_MS
        if next_decision > end_ms:
            break
        periods.append(build_period(series, entry_decision, next_decision, horizon_days, ranker=ranker))
    return periods


def periods_per_year(rebalance_hours: int) -> float:
    return 365.0 * 24.0 / rebalance_hours


def summarise(
    periods: Sequence[RebalancePeriod],
    cost_round_trip: float,
    rebalance_hours: int,
) -> dict:
    """Net annualised Sharpe and supporting diagnostics for one configuration."""
    active = [period for period in periods if period.legs]
    returns = [period.net_return(cost_round_trip) for period in active]
    if not returns:
        return {
            "decisions": 0,
            "active_periods": 0,
            "skipped_periods": len(periods),
            "net_total_return": 0.0,
            "net_sharpe": None,
            "max_drawdown": None,
        }

    scale = periods_per_year(rebalance_hours)
    sigma = pstdev(returns)
    mean_return = sum(returns) / len(returns)
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for value in returns:
        equity *= 1 + value
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1)
    gross = sum(period.gross_return for period in active)
    funding = sum(period.funding_return for period in active)
    turnover = sum(sum(abs(leg.weight) for leg in period.legs) for period in active)
    wins = [value for value in returns if value > 0]
    return {
        "decisions": len(periods),
        "active_periods": len(active),
        "skipped_periods": len(periods) - len(active),
        "daily_equivalent_observations": len(active) * rebalance_hours / 24.0,
        "net_total_return": equity - 1,
        "net_mean_period_return": mean_return,
        "net_sharpe": (mean_return / sigma * sqrt(scale)) if sigma > 0 else None,
        "net_volatility_annualised": sigma * sqrt(scale),
        "max_drawdown": max_dd,
        "positive_period_share": len(wins) / len(returns),
        "gross_return_sum": gross,
        "funding_return_sum": funding,
        "cost_drag": turnover * cost_round_trip,
        "turnover_sum": turnover,
    }


def block_bootstrap_sharpe(
    periods: Sequence[RebalancePeriod],
    cost_round_trip: float,
    rebalance_hours: int,
    *,
    iterations: int = 2000,
    seed: int = 20260821,
) -> dict:
    """Stationary block bootstrap CI for net annualised Sharpe.

    Expected block length is frozen at 14 days of rebalance periods, derived
    from the sampling frequency rather than optimised.
    """
    returns = [period.net_return(cost_round_trip) for period in periods if period.legs]
    if len(returns) < 30:
        return {"iterations": 0, "ci95_low": None, "ci95_high": None, "block_length": None}

    block_length = max(2, round(14 * 24 / rebalance_hours))
    scale = sqrt(periods_per_year(rebalance_hours))
    rng = random.Random(seed)
    n = len(returns)
    samples: list[float] = []
    for _ in range(iterations):
        drawn: list[float] = []
        while len(drawn) < n:
            start = rng.randrange(n)
            for offset in range(block_length):
                drawn.append(returns[(start + offset) % n])
                if len(drawn) >= n:
                    break
        sigma = pstdev(drawn)
        if sigma > 0:
            samples.append(sum(drawn) / len(drawn) / sigma * scale)
    if not samples:
        return {"iterations": 0, "ci95_low": None, "ci95_high": None, "block_length": block_length}
    samples.sort()
    return {
        "iterations": len(samples),
        "block_length": block_length,
        "expected_block_days": 14,
        "ci95_low": samples[int(0.025 * len(samples))],
        "ci95_high": samples[min(len(samples) - 1, int(0.975 * len(samples)))],
        "median": median(samples),
    }


def pnl_attribution(periods: Sequence[RebalancePeriod], cost_round_trip: float) -> dict:
    """Per-symbol and per-year net PnL concentration."""
    from datetime import datetime, timezone

    by_symbol: dict[str, float] = {}
    by_year: dict[str, float] = {}
    total = 0.0
    for period in periods:
        if not period.legs:
            continue
        turnover = sum(abs(leg.weight) for leg in period.legs)
        net = period.net_return(cost_round_trip)
        total += net
        year = str(datetime.fromtimestamp(period.entry_ms / 1000, tz=timezone.utc).year)
        by_year[year] = by_year.get(year, 0.0) + net
        for leg in period.legs:
            share = (abs(leg.weight) / turnover) if turnover > 0 else 0.0
            contribution = leg.weight * (leg.gross_return + leg.funding_return) - share * turnover * cost_round_trip
            by_symbol[leg.symbol] = by_symbol.get(leg.symbol, 0.0) + contribution
    denominator = abs(total) if abs(total) > 1e-12 else None
    return {
        "net_total": total,
        "by_symbol": dict(sorted(by_symbol.items())),
        "by_year": dict(sorted(by_year.items())),
        "max_symbol_share": (max(by_symbol.values()) / denominator) if denominator and by_symbol else None,
        "max_year_share": (max(by_year.values()) / denominator) if denominator and by_year else None,
    }
