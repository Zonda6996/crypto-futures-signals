from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from research.altcoin_multitf_phase4 import (
    BASE_PARTICIPATION,
    DEVELOPMENT_END_MS,
    ExchangeFilter,
    NativeBar,
    ProtocolViolation,
    adverse_price,
    annualized_metrics,
    circuit_breaker,
    closed_history,
    deflated_sharpe_probability,
    execute_next_open,
    floor_increment,
    family_a_signal,
    family_b_entries,
    hansen_spa,
    load_frozen_manifest,
    load_native_bars,
    next_open_bar,
    reject_holdout,
    resolve_stop_take,
    stationary_bootstrap_indices,
)


def bars() -> tuple[NativeBar, ...]:
    return tuple(
        NativeBar("SOLUSDT", "1h", index * 3_600_000, 100 + index, 102 + index, 98 + index, 101 + index, 10, (index + 1) * 3_600_000 - 1, 100_000)
        for index in range(4)
    )


def test_frozen_manifest_remains_exact() -> None:
    document = load_frozen_manifest(Path("reports/artifacts/altcoin-multitf-005-phase3/frozen-manifest.json"))
    assert sum(row["family"] == "A" for row in document["hypotheses"]) == 3060
    assert sum(row["family"] == "B" for row in document["hypotheses"]) == 55080


def test_holdout_and_boundary_fail_closed() -> None:
    with pytest.raises(ProtocolViolation):
        reject_holdout("data/sealed-holdout/foo.csv")
    with pytest.raises(ProtocolViolation):
        next_open_bar((NativeBar("X", "1h", DEVELOPMENT_END_MS, 1, 1, 1, 1, 1, DEVELOPMENT_END_MS + 3_599_999, 1),), DEVELOPMENT_END_MS - 1)


def test_only_closed_bars_in_signal_history_and_next_open_fill() -> None:
    sample = bars()
    assert [bar.open_time_ms for bar in closed_history(sample, 3_600_000 - 1)] == [0]
    assert next_open_bar(sample, 3_600_000 - 1).open_time_ms == 3_600_000
    assert next_open_bar(sample, 3_600_000 - 1, delay_bars=1).open_time_ms == 7_200_000


def test_adverse_rounding_and_participation() -> None:
    assert floor_increment(1.239, 0.01) == pytest.approx(1.23)
    assert adverse_price(100, "buy", 0.0002, 0.01) == pytest.approx(100.02)
    assert adverse_price(100, "sell", 0.0002, 0.01) == pytest.approx(99.98)
    fill = execute_next_open(
        symbol="SOLUSDT",
        decision_time_ms=3_600_000 - 1,
        bars=bars(),
        side="buy",
        desired_notional=10_000,
        filters=ExchangeFilter(0.01, 0.001, 0.001, 5),
        trailing_quote_volume=100_000,
    )
    assert fill.fill_time_ms == 3_600_000
    assert fill.participation <= BASE_PARTICIPATION
    assert fill.fee > 0


def test_minimum_filter_rejects_impossible_fill() -> None:
    with pytest.raises(ProtocolViolation, match="minQty"):
        execute_next_open(
            symbol="SOLUSDT",
            decision_time_ms=0,
            bars=bars(),
            side="buy",
            desired_notional=1,
            filters=ExchangeFilter(0.01, 1, 1, 100),
            trailing_quote_volume=100_000,
        )


def test_stop_first_and_circuit_breaker() -> None:
    assert resolve_stop_take(bars()[0], stop=99, take=101) == "stop"
    equity = [(0, 1.0), (31 * 86_400_000, 0.89)]
    assert circuit_breaker(equity, equity[-1][0])


def test_statistics_are_deterministic_and_finite() -> None:
    indices = stationary_bootstrap_indices(20, 3, 0.2)
    assert indices == stationary_bootstrap_indices(20, 3, 0.2)
    result = hansen_spa([[0.01, -0.01, 0.02, 0.0], [0.0, 0.0, 0.0, 0.0]], samples=99)
    assert 0 <= result["p_value"] <= 1
    assert result["resamples"] == 99
    assert 0 <= deflated_sharpe_probability(1.2, 500, 58_140) <= 1
    assert annualized_metrics([0.01, -0.005, 0.003])["max_drawdown"] < 0


def test_family_a_and_b_use_positive_causal_momentum() -> None:
    rising = tuple(NativeBar("UP", "1d", index * 86_400_000, 100 + index, 102 + index, 99 + index, 101 + index, 10, (index + 1) * 86_400_000 - 1, 100_000) for index in range(10))
    falling = tuple(NativeBar("DOWN", "1d", index * 86_400_000, 100 - index, 101 - index, 98 - index, 99 - index, 10, (index + 1) * 86_400_000 - 1, 100_000) for index in range(10))
    histories = {"UP": rising, "DOWN": falling}
    decision = rising[-1].close_time_ms
    weights = family_a_signal({"lookback_days": 7, "breadth": "top2", "weighting": "equal"}, histories, decision)
    assert weights == {"UP": pytest.approx(0.2)}
    assert family_b_entries({"lookback_days": 7, "entry": "next_open"}, histories, decision) == ("UP",)


def test_native_loader_rejects_wrong_timeframe_and_future_bar(tmp_path: Path) -> None:
    path = tmp_path / "SOLUSDT-1h.csv.gz"
    header = "open_time_ms,open,high,low,close,volume,close_time_ms,quote_volume,trade_count,taker_buy_base,taker_buy_quote\n"
    row = f"{DEVELOPMENT_END_MS},1,1,1,1,1,{DEVELOPMENT_END_MS + 3599999},1,1,1,1\n"
    with gzip.open(path, "wt") as handle:
        handle.write(header + row)
    with pytest.raises(ProtocolViolation, match="boundary"):
        load_native_bars(path, "SOLUSDT", "1h")
    with pytest.raises(ProtocolViolation, match="mismatch"):
        load_native_bars(path, "SOLUSDT", "15m")
