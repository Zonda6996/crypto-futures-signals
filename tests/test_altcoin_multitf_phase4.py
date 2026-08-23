from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.altcoin_multitf_phase3 import Candle, ExchangeRules, Family, StrategyConfig
from research.altcoin_multitf_phase4 import (
    Costs,
    FundingEvent,
    adverse_price,
    aggregate_evaluations,
    available_bar,
    evaluate_configuration,
    evaluate_signal,
    floor_to_step,
    funding_cashflow,
    validate_quantity,
)
from research.altcoin_multitf_phase4_runner import EXPECTED_GRID_COUNT, frozen_grid, run_chunks


def candles(count: int, minutes: int, *, rising: bool = True, start: int = 0) -> tuple[Candle, ...]:
    width = minutes * 60_000
    result = []
    for i in range(count):
        base = 100 + (i if rising else count - i) * 0.5
        result.append(Candle(start + i * width, start + (i + 1) * width, base, base + 1, base - 1, base + (0.25 if rising else -0.25), 1000))
    return tuple(result)


def config(family: Family = Family.A, threshold: float = 0.0) -> StrategyConfig:
    return StrategyConfig(family, 15, 240, 3, 13, threshold, 0.0, 1.5, 2.0, 12)


def rules() -> ExchangeRules:
    return ExchangeRules(0.01, 0.001, 0.001, 5.0, 1000.0)


def test_candle_rejects_bad_time_and_ohlc() -> None:
    with pytest.raises(ValueError):
        Candle(1, 1, 1, 1, 1, 1, 1)
    with pytest.raises(ValueError):
        Candle(0, 1, 2, 1, 0, 2, 1)


def test_available_bar_is_close_time_causal() -> None:
    bars = candles(3, 15)
    assert available_bar(bars, bars[1].close_time_ms - 1) == bars[0]
    assert available_bar(bars, bars[1].close_time_ms) == bars[1]


def test_signal_does_not_see_future_bar() -> None:
    signal_bars = candles(20, 15)
    regime_bars = candles(20, 240)
    decision = signal_bars[-2].close_time_ms
    original = evaluate_signal(config(), decision, signal_bars, regime_bars)
    poisoned = signal_bars[:-1] + (Candle(signal_bars[-1].open_time_ms, signal_bars[-1].close_time_ms, 1, 10000, 0, 9999, 1),)
    assert evaluate_signal(config(), decision, poisoned, regime_bars) == original


def test_family_a_and_b_are_explicit_paths() -> None:
    signal_bars = candles(400, 15)
    regime_bars = candles(30, 240)
    decision = max(signal_bars[-1].close_time_ms, regime_bars[-1].close_time_ms)
    assert evaluate_signal(config(Family.A), decision, signal_bars, regime_bars).side == 1
    assert evaluate_signal(config(Family.B, 0.001), decision, signal_bars, regime_bars).side in {0, 1}


def test_rounding_and_exchange_filters() -> None:
    assert floor_to_step(1.239, 0.01) == pytest.approx(1.23)
    buy, _ = adverse_price(100, 1, 0.1, 2)
    sell, _ = adverse_price(100, -1, 0.1, 2)
    assert buy >= 100 and sell <= 100
    assert validate_quantity(0.001, 100, rules()) == "below_min_notional"
    assert validate_quantity(0.1, 100, rules()) is None


def test_funding_sign() -> None:
    assert funding_cashflow(1, 2, 100, 0.001) == pytest.approx(-0.2)
    assert funding_cashflow(-1, 2, 100, 0.001) == pytest.approx(0.2)


def test_non_finite_market_data_is_rejected_before_evaluation() -> None:
    with pytest.raises(ValueError):
        Candle(0, 1, 1, 1, 1, float("nan"), 1)


def test_valid_insufficient_history_is_zero_trade() -> None:
    result = evaluate_configuration(config(), candles(5, 5), candles(5, 15), candles(5, 240), [], rules())
    assert result.valid and result.zero_trade


def test_deterministic_replay_and_cost_accounting() -> None:
    kwargs = dict(
        config=config(),
        execution_bars=candles(500, 5),
        signal_bars=candles(80, 15),
        regime_bars=candles(30, 240),
        funding=[FundingEvent(25 * 240 * 60_000, 0.0001)],
        rules=rules(),
        costs=Costs(),
    )
    first = evaluate_configuration(**kwargs)
    second = evaluate_configuration(**kwargs)
    assert first == second
    for trade in first.trades:
        assert trade.net_pnl == pytest.approx(trade.gross_pnl - trade.fees + trade.funding)
        assert trade.fees >= 0 and trade.slippage >= 0


def test_unordered_data_is_invalid() -> None:
    bars = candles(3, 5)
    result = evaluate_configuration(config(), reversed(bars), candles(20, 15), candles(20, 240), [], rules())
    assert not result.valid
    assert "increasing" in result.diagnostics.invalid_reason


def test_aggregate_refuses_invalid_series() -> None:
    invalid = evaluate_configuration(config(), [], [], [], [], rules(), initial_equity=-1)
    with pytest.raises(ValueError):
        aggregate_evaluations({"x": invalid})


def test_frozen_grid_count_and_unique_keys() -> None:
    grid = frozen_grid()
    assert len(grid) == EXPECTED_GRID_COUNT == 5832
    assert len({item.key for item in grid}) == len(grid)


def test_checkpoint_resume_is_idempotent(tmp_path: Path) -> None:
    subset = frozen_grid()[:3]
    calls: list[str] = []

    def evaluator(item: StrategyConfig) -> dict[str, object]:
        calls.append(item.key)
        return {"key": item.key, "valid": True}

    assert run_chunks(subset, tmp_path, evaluator, chunk_size=2)["complete"]
    assert len(calls) == 3
    assert run_chunks(subset, tmp_path, evaluator, chunk_size=2)["complete"]
    assert len(calls) == 3
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text())
    assert checkpoint["completed_keys"] == sorted(item.key for item in subset)


def test_configuration_prevents_tf_and_window_errors() -> None:
    with pytest.raises(ValueError):
        StrategyConfig(Family.A, 240, 240, 3, 13, 0, 0, 1, 2, 12)
    with pytest.raises(ValueError):
        StrategyConfig(Family.A, 15, 240, 13, 13, 0, 0, 1, 2, 12)
