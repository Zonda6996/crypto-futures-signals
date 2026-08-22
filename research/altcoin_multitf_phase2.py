from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from research.altcoin_multitf_compact import BoundaryError

TF_GROUPS = {
    "short": ("5m", "15m", "30m"),
    "medium": ("1h", "2h", "4h"),
    "long": ("1d",),
}


@dataclass(frozen=True)
class GroupParameters:
    momentum_bars: int
    volatility_bars: int
    trend_bars: int
    funding_bars: int


FROZEN_PARAMETERS = {
    "short": GroupParameters(12, 24, 48, 3),
    "medium": GroupParameters(6, 12, 24, 3),
    "long": GroupParameters(5, 10, 20, 3),
}


@dataclass(frozen=True)
class Bar:
    symbol: str
    timeframe: str
    open_time_ms: int
    close_time_ms: int
    close: float


@dataclass(frozen=True)
class FundingRecord:
    symbol: str
    publication_time_ms: int
    funding_rate: float


@dataclass(frozen=True)
class EligibilityRun:
    symbol: str
    start_ms: int
    end_exclusive_ms: int
    state: str


@dataclass(frozen=True)
class FeatureRow:
    symbol: str
    timeframe: str
    decision_time_ms: int
    return_1: float
    momentum: float
    volatility: float
    normalized_momentum: float
    trend: int
    funding: float
    ranking_input: float


@dataclass(frozen=True)
class SignalRow:
    symbol: str
    timeframe: str
    decision_time_ms: int
    score: float
    direction: int
    rank: int
    percentile: float
    eligibility_state: str


@dataclass(frozen=True)
class PortfolioCandidate:
    symbol: str
    timeframe: str
    decision_time_ms: int
    score: float
    rank: int
    direction: int


@dataclass(frozen=True)
class Diagnostics:
    input_symbols: int
    eligible_symbols: int
    featured_symbols: int
    excluded_symbols: tuple[str, ...]


def timeframe_group(timeframe: str) -> str:
    for group, members in TF_GROUPS.items():
        if timeframe in members:
            return group
    raise ValueError(f"unsupported timeframe: {timeframe}")


def _finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"non-finite {name}")
    return value


def closed_bars(bars: Iterable[Bar], *, decision_time_ms: int, timeframe: str) -> tuple[Bar, ...]:
    selected = [bar for bar in bars if bar.timeframe == timeframe and bar.close_time_ms <= decision_time_ms]
    selected.sort(key=lambda row: (row.close_time_ms, row.open_time_ms))
    if any(a.close_time_ms >= b.close_time_ms for a, b in zip(selected, selected[1:])):
        raise ValueError("bars must have unique, strictly increasing close timestamps")
    return tuple(selected)


def eligibility_at(runs: Iterable[EligibilityRun], symbol: str, decision_time_ms: int) -> str:
    states = [run.state for run in runs if run.symbol == symbol and run.start_ms <= decision_time_ms < run.end_exclusive_ms]
    if len(states) > 1:
        raise ValueError(f"overlapping eligibility runs: {symbol}")
    return states[0] if states else "ineligible"


def aligned_funding(records: Iterable[FundingRecord], *, symbol: str, decision_time_ms: int, count: int) -> float:
    available = sorted(
        (record for record in records if record.symbol == symbol and record.publication_time_ms <= decision_time_ms),
        key=lambda row: row.publication_time_ms,
    )
    if not available:
        return 0.0
    return sum(_finite(row.funding_rate, "funding_rate") for row in available[-count:])


def calculate_feature(
    symbol: str,
    timeframe: str,
    decision_time_ms: int,
    bars: Iterable[Bar],
    funding: Iterable[FundingRecord],
    *,
    parameters: Mapping[str, GroupParameters] = FROZEN_PARAMETERS,
) -> FeatureRow | None:
    group = timeframe_group(timeframe)
    params = parameters[group]
    history = closed_bars(bars, decision_time_ms=decision_time_ms, timeframe=timeframe)
    required = max(params.momentum_bars + 1, params.volatility_bars + 1, params.trend_bars)
    if len(history) < required:
        return None
    closes = [_finite(row.close, "close") for row in history]
    if any(value <= 0 for value in closes):
        raise ValueError("close must be positive")
    returns = [math.log(current / previous) for previous, current in zip(closes, closes[1:])]
    return_1 = returns[-1]
    momentum = math.log(closes[-1] / closes[-1 - params.momentum_bars])
    volatility = statistics.pstdev(returns[-params.volatility_bars:])
    normalized = momentum / volatility if volatility > 0 else 0.0
    trend_mean = statistics.fmean(closes[-params.trend_bars:])
    trend = 1 if closes[-1] > trend_mean else -1 if closes[-1] < trend_mean else 0
    funding_value = aligned_funding(funding, symbol=symbol, decision_time_ms=decision_time_ms, count=params.funding_bars)
    ranking_input = normalized * trend - funding_value
    return FeatureRow(symbol, timeframe, decision_time_ms, return_1, momentum, volatility, normalized, trend, funding_value, ranking_input)


def generate_signals(
    *,
    decision_time_ms: int,
    timeframe: str,
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding: Iterable[FundingRecord],
    eligibility: Iterable[EligibilityRun],
    parameters: Mapping[str, GroupParameters] = FROZEN_PARAMETERS,
) -> tuple[tuple[SignalRow, ...], Diagnostics]:
    if "holdout" in timeframe.lower():
        raise BoundaryError("holdout path/timeframe rejected")
    funding_rows = tuple(funding)
    eligibility_rows = tuple(eligibility)
    eligible: list[tuple[str, str]] = []
    excluded: list[str] = []
    for symbol in sorted(bars_by_symbol):
        state = eligibility_at(eligibility_rows, symbol, decision_time_ms)
        if state == "ineligible":
            excluded.append(symbol)
        else:
            eligible.append((symbol, state))
    features: list[tuple[FeatureRow, str]] = []
    for symbol, state in eligible:
        feature = calculate_feature(symbol, timeframe, decision_time_ms, bars_by_symbol[symbol], funding_rows, parameters=parameters)
        if feature is None:
            excluded.append(symbol)
        else:
            features.append((feature, state))
    features.sort(key=lambda item: (-item[0].ranking_input, item[0].symbol))
    total = len(features)
    signals = tuple(
        SignalRow(
            feature.symbol,
            timeframe,
            decision_time_ms,
            feature.ranking_input,
            1 if feature.ranking_input > 0 else -1 if feature.ranking_input < 0 else 0,
            rank,
            (total - rank + 1) / total,
            state,
        )
        for rank, (feature, state) in enumerate(features, 1)
    )
    diagnostics = Diagnostics(len(bars_by_symbol), len(eligible), len(features), tuple(sorted(set(excluded))))
    return signals, diagnostics


def portfolio_interface(signals: Iterable[SignalRow]) -> tuple[PortfolioCandidate, ...]:
    """Schema-only handoff; Phase 2 performs no sizing, construction, or PnL."""
    return tuple(PortfolioCandidate(row.symbol, row.timeframe, row.decision_time_ms, row.score, row.rank, row.direction) for row in signals)
