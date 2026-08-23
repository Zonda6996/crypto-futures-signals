"""Bit-exact accelerated evaluation path for the frozen ALTCOIN_MULTITF_005 engine.

The frozen engine in ``research.altcoin_multitf_phase4`` remains authoritative and
untouched. This module reproduces its decisions and floating-point operations
*verbatim* (same expressions, same operand order) while replacing repeated linear
scans with precomputed, identically-defined rolling statistics and compact column
storage. Every rolling statistic is computed with the exact same slice and
aggregation calls as the frozen helpers (``statistics.fmean`` over the identical
element sequence), so results are bit-for-bit identical; differential tests
enforce equivalence against ``evaluate_configuration`` on shared inputs.
"""
from __future__ import annotations

from array import array
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from math import isfinite
from statistics import fmean
from typing import Iterable, Sequence

from research.altcoin_multitf_phase3 import Candle, ExchangeRules, Family, StrategyConfig
from research.altcoin_multitf_phase4 import (
    Costs,
    Diagnostics,
    Evaluation,
    FundingEvent,
    Signal,
    Trade,
    adverse_price,
    floor_to_step,
    funding_cashflow,
    validate_quantity,
)

ATR_LENGTH = 14
WINDOWS = (3, 5, 8, 13, 21, 34)


@dataclass(frozen=True)
class CompactSeries:
    open_times_ms: array
    close_times_ms: array
    opens: array
    highs: array
    lows: array
    closes: array

    def __len__(self) -> int:
        return len(self.closes)


def build_compact(bars: Iterable[Candle]) -> CompactSeries:
    ot = array("q")
    ct = array("q")
    o = array("d")
    h = array("d")
    low = array("d")
    c = array("d")
    for bar in bars:
        ot.append(bar.open_time_ms)
        ct.append(bar.close_time_ms)
        o.append(bar.open)
        h.append(bar.high)
        low.append(bar.low)
        c.append(bar.close)
    return CompactSeries(ot, ct, o, h, low, c)


def validate_compact(series: CompactSeries) -> None:
    """Mirror the frozen validation exactly: Candle invariants + strict ordering + finiteness."""
    previous_close = None
    for index in range(len(series)):
        open_time = series.open_times_ms[index]
        close_time = series.close_times_ms[index]
        opn = series.opens[index]
        high = series.highs[index]
        low = series.lows[index]
        close = series.closes[index]
        if close_time <= open_time:
            raise ValueError("candle close must follow open")
        if not all(isfinite(v) and v >= 0 for v in (opn, high, low, close)):
            raise ValueError("negative or non-finite market data")
        if high < max(opn, close) or low > min(opn, close):
            raise ValueError("invalid OHLC envelope")
        if previous_close is not None and close_time <= previous_close:
            raise ValueError("candles must have unique increasing close times")
        previous_close = close_time


def sma_series(closes: Sequence[float], length: int) -> list[float | None]:
    """sma_series(t) == _sma(closes[:t+1], length); identical slices, identical fmean calls."""
    return [fmean(closes[i - length + 1 : i + 1]) if i >= length - 1 else None for i in range(len(closes))]


def atr_series_compact(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], length: int = ATR_LENGTH) -> list[float | None]:
    """atr_series(t) == _atr(bars[:t+1]); range expressions copied verbatim."""
    result: list[float | None] = []
    n = len(closes)
    for i in range(n):
        if i < length:
            result.append(None)
            continue
        ranges = []
        start_prev = i - length
        for j in range(length):
            prior_close = closes[start_prev + j]
            cur_high = highs[i - length + 1 + j]
            cur_low = lows[i - length + 1 + j]
            ranges.append(max(cur_high - cur_low, abs(cur_high - prior_close), abs(cur_low - prior_close)))
        result.append(fmean(ranges))
    return result


class IndicatorCache:
    """Per-process rolling-statistics cache keyed by dataset object identity."""

    def __init__(self, max_entries: int = 8, windows: tuple[int, ...] = WINDOWS) -> None:
        self._entries: dict[tuple[int, int], dict[str, object]] = {}
        self._max_entries = max_entries
        self._windows = tuple(windows)

    def _entry(self, key: tuple[int, int], builder) -> dict[str, object]:
        entry = self._entries.get(key)
        if entry is None:
            if len(self._entries) >= self._max_entries:
                del self._entries[next(iter(self._entries))]
            entry = builder()
            entry["pin"] = key[0]
            self._entries[key] = entry
        return entry

    def signal_entry(self, series_id: int, series: CompactSeries) -> dict[str, object]:
        def build() -> dict[str, object]:
            closes = list(series.closes)
            return {
                "closes": closes,
                "sma": {w: sma_series(closes, w) for w in self._windows},
                "atr": atr_series_compact(series.highs, series.lows, series.closes),
            }

        return self._entry((series_id, 0), build)

    def regime_entry(self, series_id: int, series: CompactSeries) -> dict[str, object]:
        def build() -> dict[str, object]:
            closes = list(series.closes)
            return {"closes": closes, "sma": {w: sma_series(closes, w) for w in self._windows}}

        return self._entry((series_id, 1), build)


def evaluate_signal_fast(
    config: StrategyConfig,
    decision_time_ms: int,
    signal_index: int,
    signal_entry: dict[str, object],
    regime_entry: dict[str, object],
    regime_visible_count: int,
) -> Signal | None:
    slow_window = config.slow_window
    if signal_index + 1 < slow_window + 1 or regime_visible_count < slow_window:
        return None
    signal_sma: dict[int, list[float | None]] = signal_entry["sma"]
    regime_sma: dict[int, list[float | None]] = regime_entry["sma"]
    fast = signal_sma[config.fast_window][signal_index]
    slow = signal_sma[slow_window][signal_index]
    regime_fast = regime_sma[config.fast_window][regime_visible_count - 1]
    regime_slow = regime_sma[slow_window][regime_visible_count - 1]
    atr_values: list[float | None] = signal_entry["atr"]
    atr = atr_values[signal_index]
    if None in (fast, slow, regime_fast, regime_slow, atr) or slow == 0 or atr == 0:
        return None
    regime = 1 if regime_fast > regime_slow else -1 if regime_fast < regime_slow else 0
    if config.family is Family.A:
        spread = (fast - slow) / slow
        side = 1 if spread >= config.entry_threshold and regime > 0 else -1 if spread <= -config.entry_threshold and regime < 0 else 0
        strength = abs(spread)
    else:
        deviation = (signal_entry["closes"][signal_index] - slow) / slow
        side = 1 if deviation <= -config.entry_threshold and regime > 0 else -1 if deviation >= config.entry_threshold and regime < 0 else 0
        strength = abs(deviation)
    if config.side == "long" and side < 0 or config.side == "short" and side > 0:
        side = 0
    assert atr is not None
    return Signal(decision_time_ms, side, strength, atr)


def evaluate_compact(
    config: StrategyConfig,
    execution: CompactSeries,
    signals: CompactSeries,
    regimes: CompactSeries,
    funding: Sequence[FundingEvent],
    rules: ExchangeRules,
    *,
    initial_equity: float = 10_000.0,
    risk_fraction: float = 0.1,
    costs: Costs = Costs(),
    cache: IndicatorCache | None = None,
    symbol: str = "",
    signal_tf: int = 0,
    prevalidated: bool = False,
    signal_entry: dict[str, object] | None = None,
    regime_entry: dict[str, object] | None = None,
    decision_start_ms: int | None = None,
) -> Evaluation:
    diagnostics = Diagnostics()
    try:
        if not prevalidated:
            validate_compact(execution)
            validate_compact(signals)
            validate_compact(regimes)
        if initial_equity <= 0 or not 0 < risk_fraction <= 1:
            raise ValueError("invalid capital inputs")
    except ValueError as exc:
        diagnostics.invalid_reason = str(exc)
        return Evaluation(config.key, False, (), initial_equity, diagnostics)

    funding_events = tuple(sorted(funding, key=lambda x: x.timestamp_ms))
    funding_ts = [event.timestamp_ms for event in funding_events]
    exec_opens = execution.open_times_ms
    exec_closes = execution.close_times_ms
    regime_close_times = regimes.close_times_ms

    if signal_entry is None or regime_entry is None:
        if cache is None:
            cache = IndicatorCache()
        sig_entry = cache.signal_entry(id(signals), signals)
        reg_entry = cache.regime_entry(id(regimes), regimes)
    else:
        sig_entry = signal_entry
        reg_entry = regime_entry

    equity = initial_equity
    trades: list[Trade] = []
    next_allowed_time = -1
    tick = rules.tick_size
    step = rules.step_size
    slip_bps = costs.slippage_bps
    max_holding = config.max_holding_bars
    stop_atr = config.stop_atr
    take_atr = config.take_atr
    exec_highs = execution.highs
    exec_lows = execution.lows
    n_execution = len(execution)
    sig_ct = signals.close_times_ms

    for signal_index in range(len(signals)):
        decision = sig_ct[signal_index]
        if decision < next_allowed_time:
            continue
        if decision_start_ms is not None and decision < decision_start_ms:
            continue
        regime_visible = bisect_right(regime_close_times, decision)
        signal = evaluate_signal_fast(config, decision, signal_index, sig_entry, reg_entry, regime_visible)
        if signal is None or signal.side == 0:
            continue
        side = signal.side
        entry_index = bisect_left(exec_opens, decision)
        if entry_index >= n_execution:
            diagnostics.missing_bars += 1
            continue
        entry_price, entry_slip_unit = adverse_price(execution.opens[entry_index], side, tick, slip_bps)
        quantity = floor_to_step((equity * risk_fraction) / entry_price, step)
        rejection = validate_quantity(quantity, entry_price, rules)
        if rejection:
            diagnostics.reject(rejection)
            continue
        stop = entry_price - side * stop_atr * signal.atr
        take = entry_price + side * take_atr * signal.atr
        stop_index = entry_index + max_holding
        if stop_index > n_execution:
            stop_index = n_execution
        exit_index, raw_exit, reason = stop_index - 1, execution.closes[stop_index - 1], "timeout"
        for j in range(entry_index, stop_index):
            bar_high = exec_highs[j]
            bar_low = exec_lows[j]
            stop_hit = bar_low <= stop if side > 0 else bar_high >= stop
            if stop_hit:
                exit_index, raw_exit, reason = j, stop, "stop"
                break
            take_hit = bar_high >= take if side > 0 else bar_low <= take
            if take_hit:
                exit_index, raw_exit, reason = j, take, "take"
                break
        exit_bar_open_time = exec_opens[exit_index]
        exit_bar_close_time = exec_closes[exit_index]
        exit_price, exit_slip_unit = adverse_price(raw_exit, -side, tick, slip_bps)
        fees = quantity * (entry_price + exit_price) * costs.fee_bps / 10_000
        slippage_amount = quantity * (entry_slip_unit + exit_slip_unit)
        accrued_funding = 0.0
        first_event = bisect_right(funding_ts, exec_opens[entry_index])
        last_event = bisect_right(funding_ts, exit_bar_close_time)
        for k in range(first_event, last_event):
            event = funding_events[k]
            mark_index = bisect_right(exec_closes, event.timestamp_ms) - 1
            if mark_index < 0:
                diagnostics.missing_bars += 1
                continue
            accrued_funding += funding_cashflow(side, quantity, execution.closes[mark_index], event.rate)
            diagnostics.funding_events += 1
        gross = side * quantity * (exit_price - entry_price)
        net = gross - fees + accrued_funding
        equity_before = equity
        equity += net
        trades.append(
            Trade(
                side,
                quantity,
                exec_opens[entry_index],
                exit_bar_close_time,
                entry_price,
                exit_price,
                gross,
                fees,
                slippage_amount,
                accrued_funding,
                net,
                net / equity_before,
                reason,
            )
        )
        next_allowed_time = exit_bar_close_time
        if not isfinite(equity) or equity <= 0:
            diagnostics.invalid_reason = "non-positive or non-finite equity"
            return Evaluation(config.key, False, tuple(trades), equity, diagnostics)
    return Evaluation(config.key, True, tuple(trades), equity, diagnostics)
