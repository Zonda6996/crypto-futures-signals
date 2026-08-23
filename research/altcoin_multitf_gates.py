"""Metrics, gates and deterministic ordering for ALTCOIN_MULTITF_005 Part 2.

Every definition here implements the frozen protocol text conservatively; where
the protocol is silent the most conservative defensible reading is used and
documented in the Part 2 handoff. Nothing may be relaxed to produce a winner.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import median
from typing import Mapping, Sequence

from research.altcoin_multitf_phase3 import Family, StrategyConfig
from research.altcoin_multitf_phase4 import Trade
from research.altcoin_multitf_statistics import sharpe_ratio

DEV_START_MS = 1_609_459_200_000
DEV_END_MS = 1_704_067_200_000
DAY_MS = 86_400_000
DEV_DAYS = (DEV_END_MS - DEV_START_MS) // DAY_MS
ANNUALIZATION = sqrt(365.0)
FOLD_COUNT = 6
ELIGIBILITY_MIN_TRADES = 100
ELIGIBILITY_MIN_SHARPE = 0.5
ELIGIBILITY_MAX_DRAWDOWN = -0.25
ELIGIBILITY_MIN_ACTIVE_ASSETS = 6
CONCENTRATION_LIMIT = 0.40
NEIGHBOR_MIN_PROFITABLE_SHARE = 0.60
TEMPORAL_MIN_POSITIVE_FOLDS = 4
SPA_P_LIMIT = 0.05
DSR_PROBABILITY_LIMIT = 0.95
HOLM_P_LIMIT = 0.05


def fold_bounds(start_ms: int = DEV_START_MS, end_ms: int = DEV_END_MS, count: int = FOLD_COUNT) -> list[tuple[int, int]]:
    step = (end_ms - start_ms) // count
    return [(start_ms + index * step, start_ms + (index + 1) * step) for index in range(count)]


@dataclass(frozen=True)
class ConfigMetrics:
    config_key: str
    valid: bool
    zero_trade: bool
    invalid_reason: str | None
    trades: int
    net_pnl: float
    net_return: float
    mean_trade_return: float
    daily_sharpe: float | None
    annualized_sharpe: float | None
    median_fold_sharpe: float
    fold_sharpes: tuple[float, ...]
    fold_net_returns: tuple[float, ...]
    positive_folds: int
    max_drawdown: float
    active_assets: int
    asset_names: tuple[str, ...]
    max_asset_positive_share: float
    long_trades: int
    short_trades: int
    long_net_pnl: float
    short_net_pnl: float
    ending_equity: float
    rejected_orders_total: int
    missing_bars: int
    funding_events: int
    daily_returns: tuple[float, ...]


def _empty_daily() -> list[float]:
    return [0.0] * DEV_DAYS


def daily_equity_curve(
    events: Sequence[tuple[int, str, int, float]],
    initial_equity: float,
    *,
    start_ms: int = DEV_START_MS,
    end_ms: int = DEV_END_MS,
) -> list[float]:
    """End-of-day equity for a merged cross-symbol trade event stream.

    ``events`` items are ``(exit_time_ms, symbol, entry_time_ms, net_pnl)``
    sorted by ``(exit_time_ms, symbol, entry_time_ms)``.
    """
    days = (end_ms - start_ms) // DAY_MS
    points: list[tuple[int, float]] = []
    equity = initial_equity
    for exit_time_ms, _symbol, _entry_time_ms, net_pnl in events:
        day = (exit_time_ms - start_ms) // DAY_MS
        if day < 0 or day >= days:
            continue
        equity += net_pnl
        points.append((day, equity))
    curve: list[float] = []
    index = 0
    running = initial_equity
    for day in range(days):
        while index < len(points) and points[index][0] == day:
            running = points[index][1]
            index += 1
        curve.append(running)
    return curve


def daily_returns_from_curve(curve: Sequence[float], initial_equity: float) -> list[float]:
    returns = []
    previous = initial_equity
    for equity in curve:
        returns.append(0.0 if previous <= 0 else equity / previous - 1.0)
        previous = equity
    return returns


def max_drawdown_from_curve(curve: Sequence[float]) -> float:
    peak = curve[0] if curve else 0.0
    worst = 0.0
    for equity in curve:
        if equity > peak:
            peak = equity
        if peak > 0:
            drawdown = equity / peak - 1.0
            if drawdown < worst:
                worst = drawdown
    return worst


def compute_metrics(
    config_key: str,
    evaluation_by_symbol: Mapping[str, object],
    *,
    initial_equity: float,
    window_start_ms: int = DEV_START_MS,
    window_end_ms: int = DEV_END_MS,
    fold_count: int = FOLD_COUNT,
) -> ConfigMetrics:
    """Aggregate per-symbol frozen-engine evaluations into protocol metrics.

    ``evaluation_by_symbol`` maps symbol -> Evaluation from the frozen engine.
    Trades must already be filtered by the caller to entries inside the accounting
    window when a warmup-inclusive engine span was used.
    """
    events: list[tuple[int, str, int, float]] = []
    asset_positive: dict[str, float] = {}
    asset_any: dict[str, bool] = {}
    long_net = short_net = 0.0
    long_trades = short_trades = 0
    total_net = 0.0
    trade_count = 0
    return_sum = 0.0
    invalid_reason = None
    missing_bars = 0
    rejected_total = 0
    funding_events_count = 0
    fold_nets = [0.0] * fold_count
    bounds = fold_bounds(window_start_ms, window_end_ms, fold_count)
    ending_equity = initial_equity
    for symbol in sorted(evaluation_by_symbol):
        evaluation = evaluation_by_symbol[symbol]
        if not evaluation.valid:
            invalid_reason = evaluation.diagnostics.invalid_reason or "invalid"
            break
        missing_bars += evaluation.diagnostics.missing_bars
        rejected_total += sum(evaluation.diagnostics.rejected_orders.values())
        funding_events_count += evaluation.diagnostics.funding_events
        ending_equity = evaluation.ending_equity
        for trade in evaluation.trades:
            trade_count += 1
            total_net += trade.net_pnl
            return_sum += trade.return_on_equity
            events.append((trade.exit_time_ms, symbol, trade.entry_time_ms, trade.net_pnl))
            asset_any[symbol] = True
            if trade.net_pnl > 0:
                asset_positive[symbol] = asset_positive.get(symbol, 0.0) + trade.net_pnl
            if trade.side > 0:
                long_trades += 1
                long_net += trade.net_pnl
            else:
                short_trades += 1
                short_net += trade.net_pnl
            for index, (start, end) in enumerate(bounds):
                if start <= trade.exit_time_ms < end:
                    fold_nets[index] += trade.net_pnl
                    break
    if invalid_reason is not None:
        window_days = (window_end_ms - window_start_ms) // DAY_MS
        return ConfigMetrics(
            config_key=config_key,
            valid=False,
            zero_trade=False,
            invalid_reason=invalid_reason,
            trades=trade_count,
            net_pnl=total_net,
            net_return=total_net / initial_equity,
            mean_trade_return=return_sum / trade_count if trade_count else 0.0,
            daily_sharpe=None,
            annualized_sharpe=None,
            median_fold_sharpe=0.0,
            fold_sharpes=tuple([0.0] * fold_count),
            fold_net_returns=tuple(fold_nets),
            positive_folds=0,
            max_drawdown=0.0,
            active_assets=len(asset_any),
            asset_names=tuple(sorted(asset_any)),
            max_asset_positive_share=1.0,
            long_trades=long_trades,
            short_trades=short_trades,
            long_net_pnl=long_net,
            short_net_pnl=short_net,
            ending_equity=ending_equity,
            rejected_orders_total=rejected_total,
            missing_bars=missing_bars,
            funding_events=funding_events_count,
            daily_returns=tuple([0.0] * window_days),
        )
    events.sort(key=lambda item: (item[0], item[1], item[2]))
    curve = daily_equity_curve(events, initial_equity, start_ms=window_start_ms, end_ms=window_end_ms)
    daily = daily_returns_from_curve(curve, initial_equity)
    daily_sharpe = sharpe_ratio(daily)
    bounds_list = bounds
    fold_sharpes: list[float] = []
    for start, end in bounds_list:
        first_day = (start - window_start_ms) // DAY_MS
        last_day = (end - window_start_ms) // DAY_MS
        segment = daily[first_day:last_day]
        fold_sharpe = sharpe_ratio(segment)
        fold_sharpes.append(0.0 if fold_sharpe is None else fold_sharpe * ANNUALIZATION)
    positive_pnl_total = sum(asset_positive.values())
    max_share = max(asset_positive.values()) / positive_pnl_total if positive_pnl_total > 0 else 1.0
    net_return = total_net / initial_equity
    metrics = ConfigMetrics(
        config_key=config_key,
        valid=True,
        zero_trade=trade_count == 0,
        invalid_reason=None,
        trades=trade_count,
        net_pnl=total_net,
        net_return=net_return,
        mean_trade_return=return_sum / trade_count if trade_count else 0.0,
        daily_sharpe=daily_sharpe,
        annualized_sharpe=None if daily_sharpe is None else daily_sharpe * ANNUALIZATION,
        median_fold_sharpe=median(fold_sharpes),
        fold_sharpes=tuple(fold_sharpes),
        fold_net_returns=tuple(value / initial_equity for value in fold_nets),
        positive_folds=sum(1 for value in fold_sharpes if value > 0),
        max_drawdown=max_drawdown_from_curve(curve),
        active_assets=len(asset_any),
        asset_names=tuple(sorted(asset_any)),
        max_asset_positive_share=max_share,
        long_trades=long_trades,
        short_trades=short_trades,
        long_net_pnl=long_net,
        short_net_pnl=short_net,
        ending_equity=ending_equity,
        rejected_orders_total=rejected_total,
        missing_bars=missing_bars,
        funding_events=funding_events_count,
        daily_returns=tuple(daily),
    )
    return metrics


def eligibility_report(metrics: ConfigMetrics) -> dict[str, bool]:
    sharpe_ok = metrics.annualized_sharpe is not None and metrics.annualized_sharpe > ELIGIBILITY_MIN_SHARPE
    concentration_ok = metrics.trades > 0 and metrics.max_asset_positive_share <= CONCENTRATION_LIMIT
    return {
        "trades": metrics.trades >= ELIGIBILITY_MIN_TRADES,
        "positive_net_return": metrics.net_return > 0,
        "sharpe": sharpe_ok,
        "drawdown": metrics.max_drawdown >= ELIGIBILITY_MAX_DRAWDOWN,
        "coverage": metrics.active_assets >= ELIGIBILITY_MIN_ACTIVE_ASSETS,
        "concentration": concentration_ok,
    }


def is_eligible(metrics: ConfigMetrics) -> bool:
    return metrics.valid and all(eligibility_report(metrics).values())


def ordering_key(metrics: ConfigMetrics) -> tuple:
    """Frozen deterministic ordering; descending on performance fields, key ascending."""
    eligible = is_eligible(metrics)
    median_fold = metrics.median_fold_sharpe
    aggregate = metrics.annualized_sharpe if metrics.annualized_sharpe is not None else float("-inf")
    net_return = metrics.net_return
    drawdown = metrics.max_drawdown
    return (
        0 if eligible else 1,
        -median_fold,
        -aggregate,
        -net_return,
        -drawdown,
        metrics.config_key,
    )


def parameter_neighbors(grid: Sequence[StrategyConfig]) -> dict[str, set[str]]:
    """Neighbors differ in exactly one grid axis; regime timeframe is fixed."""
    by_key = {config.key: config for config in grid}
    axes = ("family", "signal_tf_minutes", "fast_window", "slow_window", "entry_threshold", "exit_threshold", "stop_atr", "take_atr", "max_holding_bars")
    values_per_axis = {
        "family": sorted({config.family.value for config in grid}),
        "signal_tf_minutes": sorted({config.signal_tf_minutes for config in grid}),
        "fast_window": sorted({config.fast_window for config in grid}),
        "slow_window": sorted({config.slow_window for config in grid}),
        "entry_threshold": sorted({config.entry_threshold for config in grid}),
        "exit_threshold": sorted({config.exit_threshold for config in grid}),
        "stop_atr": sorted({config.stop_atr for config in grid}),
        "take_atr": sorted({config.take_atr for config in grid}),
        "max_holding_bars": sorted({config.max_holding_bars for config in grid}),
    }
    neighbors: dict[str, set[str]] = {key: set() for key in by_key}
    for key, config in by_key.items():
        payload = {axis: getattr(config, axis) for axis in axes if axis != "family"}
        payload["family"] = config.family.value
        for axis in axes:
            for value in values_per_axis[axis]:
                if value == payload[axis]:
                    continue
                candidate = dict(payload)
                candidate[axis] = value
                family_value = candidate.pop("family")
                try:
                    variant = StrategyConfig(
                        Family.A if family_value == "A" else Family.B,
                        candidate["signal_tf_minutes"],
                        config.regime_tf_minutes,
                        candidate["fast_window"],
                        candidate["slow_window"],
                        candidate["entry_threshold"],
                        candidate["exit_threshold"],
                        candidate["stop_atr"],
                        candidate["take_atr"],
                        candidate["max_holding_bars"],
                        config.side,
                    )
                except ValueError:
                    continue
                neighbor_key = variant.key
                if neighbor_key in by_key and neighbor_key != key:
                    neighbors[key].add(neighbor_key)
    return neighbors


def neighbor_profitability(
    key: str,
    neighbors: Mapping[str, set[str]],
    results: Mapping[str, ConfigMetrics],
) -> dict[str, float | int | bool]:
    evaluated = [results[neighbor] for neighbor in sorted(neighbors.get(key, ()))]
    valid_neighbors = [item for item in evaluated if item.valid]
    profitable = sum(1 for item in valid_neighbors if item.net_return > 0)
    denominator = len(valid_neighbors)
    share = profitable / denominator if denominator else 0.0
    return {
        "neighbors_total": len(neighbors.get(key, ())),
        "neighbors_evaluated_valid": denominator,
        "neighbors_profitable": profitable,
        "profitable_share": share,
        "gate_pass": denominator > 0 and share >= NEIGHBOR_MIN_PROFITABLE_SHARE,
    }
