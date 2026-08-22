from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import sqrt
from statistics import mean, pstdev
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Bar:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    taker_buy_volume: float = 0.0


@dataclass(frozen=True)
class Trade:
    side: int
    signal_ts: int
    entry_ts: int
    exit_ts: int
    entry: float
    exit: float
    bars_held: int
    gross_return: float
    funding_return: float
    cost_return: float
    net_return: float
    exit_reason: str


@dataclass(frozen=True)
class CostModel:
    taker_fee_bps: float = 5.0
    half_spread_bps: float = 1.0
    slippage_bps: float = 2.0

    @property
    def round_trip_return(self) -> float:
        return 2 * (self.taker_fee_bps + self.half_spread_bps + self.slippage_bps) / 10_000


@dataclass(frozen=True)
class ExitRules:
    max_bars: int
    stop_atr: float | None = None
    take_atr: float | None = None


def chronological_splits(length: int, train: float = 0.60, validation: float = 0.20) -> dict[str, range]:
    if length < 3 or train <= 0 or validation <= 0 or train + validation >= 1:
        raise ValueError("invalid chronological split")
    train_end = int(length * train)
    validation_end = int(length * (train + validation))
    return {
        "train": range(0, train_end),
        "validation": range(train_end, validation_end),
        "test": range(validation_end, length),
    }


def assert_selection_indices(indices: Iterable[int], splits: dict[str, range]) -> None:
    test = set(splits["test"])
    if any(i in test for i in indices):
        raise RuntimeError("sealed TEST data cannot be used during candidate selection")


def backward_asof(primary_ts: Sequence[int], observations: Sequence[tuple[int, float]], lag_ms: int = 0) -> list[float | None]:
    ordered = sorted(observations)
    result: list[float | None] = []
    j = 0
    last: float | None = None
    for ts in primary_ts:
        available_at = ts - lag_ms
        while j < len(ordered) and ordered[j][0] <= available_at:
            last = ordered[j][1]
            j += 1
        result.append(last)
    return result


def forward_return_target(bars: Sequence[Bar], horizon: int, execution_delay: int = 1) -> list[float | None]:
    """Target entered at next-bar open and exited at a later open; never at signal close."""
    target: list[float | None] = [None] * len(bars)
    for i in range(len(bars)):
        entry_i = i + execution_delay
        exit_i = entry_i + horizon
        if exit_i < len(bars):
            target[i] = bars[exit_i].open / bars[entry_i].open - 1
    return target


def simulate_trade(
    bars: Sequence[Bar],
    signal_index: int,
    side: int,
    atr: float,
    rules: ExitRules,
    costs: CostModel,
    funding_by_ts: dict[int, float] | None = None,
    execution_delay: int = 1,
) -> Trade | None:
    if side not in (-1, 1):
        return None
    entry_i = signal_index + execution_delay
    if entry_i >= len(bars):
        return None
    entry = bars[entry_i].open
    stop = entry - side * rules.stop_atr * atr if rules.stop_atr else None
    take = entry + side * rules.take_atr * atr if rules.take_atr else None
    end_i = min(entry_i + rules.max_bars, len(bars) - 1)
    exit_i, exit_price, reason = end_i, bars[end_i].close, "time"
    for i in range(entry_i, end_i + 1):
        bar = bars[i]
        stop_hit = stop is not None and (bar.low <= stop if side == 1 else bar.high >= stop)
        take_hit = take is not None and (bar.high >= take if side == 1 else bar.low <= take)
        if stop_hit:  # conservative collision policy: stop wins
            exit_i, exit_price, reason = i, float(stop), "stop"
            break
        if take_hit:
            exit_i, exit_price, reason = i, float(take), "take"
            break
    gross = side * (exit_price / entry - 1)
    funding = 0.0
    if funding_by_ts:
        for i in range(entry_i, exit_i + 1):
            funding -= side * funding_by_ts.get(bars[i].ts, 0.0)
    cost = costs.round_trip_return
    return Trade(side, bars[signal_index].ts, bars[entry_i].ts, bars[exit_i].ts, entry, exit_price,
                 exit_i - entry_i + 1, gross, funding, cost, gross + funding - cost, reason)


def metrics(trades: Sequence[Trade], bars_per_year: int = 24 * 365) -> dict[str, float | int | None]:
    returns = [t.net_return for t in trades]
    if not returns:
        return {"trades": 0, "expectancy": None, "profit_factor": None, "sharpe": None, "max_drawdown": None}
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for r in returns:
        equity *= 1 + r
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1)
    sigma = pstdev(returns)
    avg_hold = mean(t.bars_held for t in trades)
    return {
        "trades": len(trades),
        "win_rate": len(wins) / len(returns),
        "average_win": mean(wins) if wins else 0.0,
        "average_loss": mean(losses) if losses else 0.0,
        "expectancy": mean(returns),
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "sharpe": mean(returns) / sigma * sqrt(bars_per_year / avg_hold) if sigma else None,
        "max_drawdown": max_dd,
        "average_holding_bars": avg_hold,
        "total_return": equity - 1,
    }


def utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
