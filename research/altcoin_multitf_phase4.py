"""Causal TF-native execution engine for ALTCOIN_MULTITF_005 Phase 4."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import floor, isfinite
from statistics import fmean
from typing import Iterable, Mapping, Sequence

from research.altcoin_multitf_phase3 import (
    Candle,
    ExchangeRules,
    Family,
    StrategyConfig,
    assert_strictly_ordered,
)


@dataclass(frozen=True)
class Costs:
    fee_bps: float = 4.0
    slippage_bps: float = 2.0


@dataclass(frozen=True)
class FundingEvent:
    timestamp_ms: int
    rate: float


@dataclass(frozen=True)
class Signal:
    decision_time_ms: int
    side: int
    strength: float
    atr: float


@dataclass(frozen=True)
class Trade:
    side: int
    quantity: float
    entry_time_ms: int
    exit_time_ms: int
    entry_price: float
    exit_price: float
    gross_pnl: float
    fees: float
    slippage: float
    funding: float
    net_pnl: float
    return_on_equity: float
    exit_reason: str


@dataclass
class Diagnostics:
    invalid_reason: str | None = None
    rejected_orders: dict[str, int] = field(default_factory=dict)
    missing_bars: int = 0
    funding_events: int = 0

    def reject(self, reason: str) -> None:
        self.rejected_orders[reason] = self.rejected_orders.get(reason, 0) + 1


@dataclass(frozen=True)
class Evaluation:
    config_key: str
    valid: bool
    trades: tuple[Trade, ...]
    ending_equity: float
    diagnostics: Diagnostics

    @property
    def zero_trade(self) -> bool:
        return self.valid and not self.trades


def floor_to_step(value: float, step: float) -> float:
    if not isfinite(value) or step <= 0:
        raise ValueError("non-finite value or invalid step")
    return floor((value + step * 1e-12) / step) * step


def adverse_price(price: float, side: int, tick: float, slippage_bps: float) -> tuple[float, float]:
    """Return tick-rounded execution price and absolute slippage per unit."""
    if side not in {-1, 1} or price <= 0 or tick <= 0:
        raise ValueError("invalid execution inputs")
    slipped = price * (1 + side * slippage_bps / 10_000)
    units = slipped / tick
    rounded = (floor(units + 1 - 1e-12) if side > 0 else floor(units + 1e-12)) * tick
    return rounded, abs(rounded - price)


def validate_quantity(quantity: float, price: float, rules: ExchangeRules) -> str | None:
    if not isfinite(quantity) or not isfinite(price) or quantity <= 0 or price <= 0:
        return "non_finite_or_non_positive"
    if quantity + 1e-12 < rules.min_qty:
        return "below_min_qty"
    if rules.max_qty is not None and quantity > rules.max_qty + 1e-12:
        return "above_max_qty"
    if quantity * price + 1e-12 < rules.min_notional:
        return "below_min_notional"
    return None


def available_bar(candles: Sequence[Candle], decision_time_ms: int) -> Candle | None:
    """Latest closed bar; a currently-forming bar is never visible."""
    result = None
    for candle in candles:
        if candle.close_time_ms <= decision_time_ms:
            result = candle
        else:
            break
    return result


def next_execution_bar(candles: Sequence[Candle], decision_time_ms: int) -> Candle | None:
    return next((bar for bar in candles if bar.open_time_ms >= decision_time_ms), None)


def _sma(values: Sequence[float], length: int) -> float | None:
    return fmean(values[-length:]) if len(values) >= length else None


def _atr(candles: Sequence[Candle], length: int = 14) -> float | None:
    if len(candles) < length + 1:
        return None
    ranges = []
    for previous, current in zip(candles[-length - 1 : -1], candles[-length:]):
        ranges.append(max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close)))
    return fmean(ranges)


def evaluate_signal(
    config: StrategyConfig,
    decision_time_ms: int,
    signal_bars: Sequence[Candle],
    regime_bars: Sequence[Candle],
) -> Signal | None:
    signal_visible = [b for b in signal_bars if b.close_time_ms <= decision_time_ms]
    regime_visible = [b for b in regime_bars if b.close_time_ms <= decision_time_ms]
    if len(signal_visible) < config.slow_window + 1 or len(regime_visible) < config.slow_window:
        return None
    closes = [b.close for b in signal_visible]
    regime_closes = [b.close for b in regime_visible]
    fast, slow = _sma(closes, config.fast_window), _sma(closes, config.slow_window)
    regime_fast = _sma(regime_closes, config.fast_window)
    regime_slow = _sma(regime_closes, config.slow_window)
    atr = _atr(signal_visible)
    if None in (fast, slow, regime_fast, regime_slow, atr) or slow == 0 or atr == 0:
        return None
    regime = 1 if regime_fast > regime_slow else -1 if regime_fast < regime_slow else 0
    if config.family is Family.A:
        spread = (fast - slow) / slow
        side = 1 if spread >= config.entry_threshold and regime > 0 else -1 if spread <= -config.entry_threshold and regime < 0 else 0
        strength = abs(spread)
    else:
        deviation = (closes[-1] - slow) / slow
        side = 1 if deviation <= -config.entry_threshold and regime > 0 else -1 if deviation >= config.entry_threshold and regime < 0 else 0
        strength = abs(deviation)
    if config.side == "long" and side < 0 or config.side == "short" and side > 0:
        side = 0
    return Signal(decision_time_ms, side, strength, atr)


def funding_cashflow(side: int, quantity: float, mark_price: float, rate: float) -> float:
    if not all(isfinite(v) for v in (quantity, mark_price, rate)):
        raise ValueError("non-finite funding input")
    return -(side * quantity * mark_price) * rate


def evaluate_configuration(
    config: StrategyConfig,
    execution_bars: Iterable[Candle],
    signal_bars: Iterable[Candle],
    regime_bars: Iterable[Candle],
    funding: Iterable[FundingEvent],
    rules: ExchangeRules,
    *,
    initial_equity: float = 10_000.0,
    risk_fraction: float = 0.1,
    costs: Costs = Costs(),
) -> Evaluation:
    diagnostics = Diagnostics()
    try:
        execution = assert_strictly_ordered(execution_bars)
        signals = assert_strictly_ordered(signal_bars)
        regimes = assert_strictly_ordered(regime_bars)
        funding_events = tuple(sorted(funding, key=lambda x: x.timestamp_ms))
        if initial_equity <= 0 or not 0 < risk_fraction <= 1:
            raise ValueError("invalid capital inputs")
        values = [v for bar in (*execution, *signals, *regimes) for v in asdict(bar).values()]
        if not all(isfinite(v) for v in values):
            raise ValueError("non-finite market data")
    except ValueError as exc:
        diagnostics.invalid_reason = str(exc)
        return Evaluation(config.key, False, (), initial_equity, diagnostics)

    equity = initial_equity
    trades: list[Trade] = []
    next_allowed_time = -1
    for signal_bar in signals:
        if signal_bar.close_time_ms < next_allowed_time:
            continue
        signal = evaluate_signal(config, signal_bar.close_time_ms, signals, regimes)
        if signal is None or signal.side == 0:
            continue
        entry_bar = next_execution_bar(execution, signal.decision_time_ms)
        if entry_bar is None:
            diagnostics.missing_bars += 1
            continue
        entry_price, entry_slip_unit = adverse_price(entry_bar.open, signal.side, rules.tick_size, costs.slippage_bps)
        quantity = floor_to_step((equity * risk_fraction) / entry_price, rules.step_size)
        rejection = validate_quantity(quantity, entry_price, rules)
        if rejection:
            diagnostics.reject(rejection)
            continue
        stop = entry_price - signal.side * config.stop_atr * signal.atr
        take = entry_price + signal.side * config.take_atr * signal.atr
        candidates = [b for b in execution if b.open_time_ms >= entry_bar.open_time_ms][: config.max_holding_bars]
        if not candidates:
            diagnostics.missing_bars += 1
            continue
        exit_bar, reason = candidates[-1], "timeout"
        raw_exit = exit_bar.close
        for bar in candidates:
            stop_hit = bar.low <= stop if signal.side > 0 else bar.high >= stop
            take_hit = bar.high >= take if signal.side > 0 else bar.low <= take
            if stop_hit:  # conservative ordering when both touch in the same bar
                exit_bar, raw_exit, reason = bar, stop, "stop"
                break
            if take_hit:
                exit_bar, raw_exit, reason = bar, take, "take"
                break
        exit_price, exit_slip_unit = adverse_price(raw_exit, -signal.side, rules.tick_size, costs.slippage_bps)
        fees = quantity * (entry_price + exit_price) * costs.fee_bps / 10_000
        slippage = quantity * (entry_slip_unit + exit_slip_unit)
        accrued_funding = 0.0
        for event in funding_events:
            if entry_bar.open_time_ms < event.timestamp_ms <= exit_bar.close_time_ms:
                mark_bar = available_bar(execution, event.timestamp_ms)
                if mark_bar is None:
                    diagnostics.missing_bars += 1
                    continue
                accrued_funding += funding_cashflow(signal.side, quantity, mark_bar.close, event.rate)
                diagnostics.funding_events += 1
        gross = signal.side * quantity * (exit_price - entry_price)
        net = gross - fees + accrued_funding
        equity_before = equity
        equity += net
        trades.append(Trade(signal.side, quantity, entry_bar.open_time_ms, exit_bar.close_time_ms, entry_price, exit_price, gross, fees, slippage, accrued_funding, net, net / equity_before, reason))
        next_allowed_time = exit_bar.close_time_ms
        if not isfinite(equity) or equity <= 0:
            diagnostics.invalid_reason = "non-positive or non-finite equity"
            return Evaluation(config.key, False, tuple(trades), equity, diagnostics)
    return Evaluation(config.key, True, tuple(trades), equity, diagnostics)


def aggregate_evaluations(evaluations: Mapping[str, Evaluation]) -> dict[str, float | int]:
    ordered = [evaluations[key] for key in sorted(evaluations)]
    if any(not item.valid for item in ordered):
        raise ValueError("invalid evaluations cannot be aggregated with valid returns")
    trades = [trade for item in ordered for trade in item.trades]
    return {
        "configurations": len(ordered),
        "trades": len(trades),
        "net_pnl": sum((trade.net_pnl for trade in trades), 0.0),
        "mean_trade_return": fmean([trade.return_on_equity for trade in trades]) if trades else 0.0,
    }
