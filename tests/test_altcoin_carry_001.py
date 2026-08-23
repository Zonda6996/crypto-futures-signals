"""ALTCOIN_CARRY_001 tests: grid, signals, simulation recursion, gates, plumbing.

All tests use synthetic data or committed repository artifacts only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.altcoin_carry_001 import (
    DAY_MS,
    DECIDE_END_EXCLUSIVE_MS,
    DECIDE_START_MS,
    EXPECTED_GRID_COUNT,
    FOLD_POSITIONS,
    CarryData,
    CarryError,
    PRIMARY_TRADE_COST,
    STRESS_TRADE_COSTS,
    config_key,
    config_metrics,
    frozen_grid,
    is_eligible,
    main,
    max_drawdown_from_returns,
    neighbor_keys,
    neighbor_profitability,
    run_sweep,
    simulate,
)
import research.altcoin_carry_001 as carry

SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
)


# ---------------------------------------------------------------------------
# helpers


def synthetic_data(days: int, *, rate: float = 0.0, jump_symbol: str | None = None, jump: float = 0.0) -> CarryData:
    start = DECIDE_START_MS
    closes = {}
    funding = {}
    counts = {}
    firsts = {}
    for i, symbol in enumerate(SYMBOLS):
        closes[symbol] = {start + t * DAY_MS - DAY_MS: 100.0 for t in range(days + 1)}
        for t in range(days):
            day = start + t * DAY_MS
            if symbol == jump_symbol and t >= 1:
                closes[symbol][day] = 100.0 * (1.0 + jump)
        closes[symbol][start + days * DAY_MS] = 100.0 * (1.0 + jump) if symbol == jump_symbol else 100.0
        funding[symbol] = {}
        counts[symbol] = {}
        for t in range(days):
            day = start + t * DAY_MS
            funding[symbol][day] = rate
            counts[symbol][day] = 3
        firsts[symbol] = start if days else (1 << 62)
    return CarryData(closes, funding, counts, firsts)


# ---------------------------------------------------------------------------
# frozen grid


def test_frozen_grid_count_and_axes() -> None:
    grid = frozen_grid()
    assert len(grid) == EXPECTED_GRID_COUNT == 12
    keys = [config_key(c) for c in grid]
    assert len(set(keys)) == len(keys) and keys == sorted(keys)
    assert {(c["lookback_days"], c["k_per_side"], c["rebal_days"]) for c in grid} == {
        (lb, k, rb) for lb in (1, 3, 7) for k in (2, 3) for rb in (1, 7)
    }


def test_validate_grid_cli(tmp_path, capsys) -> None:
    assert main(["--validate-grid"]) == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["count"] == 12
    assert payload["seed"] == 20260914


# ---------------------------------------------------------------------------
# signals


def _tiny_data() -> CarryData:
    closes = {s: {} for s in SYMBOLS}
    funding = {s: {} for s in SYMBOLS}
    counts = {s: {} for s in SYMBOLS}
    day0 = DECIDE_START_MS
    for symbol in SYMBOLS:
        for offset in range(10):
            closes[symbol][day0 + offset * DAY_MS] = 100.0 + offset
            closes[symbol][day0 + offset * DAY_MS - DAY_MS] = 100.0
        funding[symbol] = {day0: 0.0009, day0 + DAY_MS: 0.0006}
        counts[symbol] = {day0: 3, day0 + DAY_MS: 1}
    return CarryData(
        closes, funding, counts,
        {s: DECIDE_START_MS - 5 * DAY_MS for s in SYMBOLS},
    )


def test_signal_is_mean_over_events_not_days() -> None:
    data = _tiny_data()
    # day0 window contains 3 events of 0.0003 -> mean per event
    assert data.signal("BTCUSDT", DECIDE_START_MS, 1) == pytest.approx(0.0003)
    # lookback=2 over days with 3 and 1 events: mean of four event rates
    expected = (3 * 0.0003 + 1 * 0.0006) / 4
    assert data.signal("BTCUSDT", DECIDE_START_MS + DAY_MS, 2) == pytest.approx(expected)


def test_signal_invalid_without_enough_history() -> None:
    data = _tiny_data()
    data.funding_first_ts["BTCUSDT"] = DECIDE_START_MS + DAY_MS
    assert data.signal("BTCUSDT", DECIDE_START_MS, 1) is None
    assert data.signal("ETHUSDT", DECIDE_START_MS, 1) is not None


# ---------------------------------------------------------------------------
# simulation recursion


def test_entry_cost_and_dollar_neutrality() -> None:
    data = synthetic_data(days=9)
    result = simulate({"lookback_days": 1, "k_per_side": 3, "rebal_days": 7}, data, PRIMARY_TRADE_COST)
    assert result["valid"]
    # entry at close of first day charges cost on full gross turnover of 1.0
    assert result["daily_returns"][0] == pytest.approx(-PRIMARY_TRADE_COST)
    # flat prices and identical funding cancel across shorts/longs
    assert all(abs(r) < 1e-12 for r in result["daily_returns"][1:])
    fractions = result["final_fractions"]
    assert sum(fractions.values()) == pytest.approx(0.0, abs=1e-12)
    assert sum(abs(v) for v in fractions.values()) == pytest.approx(1.0)
    shorts = {s for s, v in fractions.items() if v < 0}
    longs = {s for s, v in fractions.items() if v > 0}
    assert len(shorts) == len(longs) == 3
    # ties broken by symbol ascending: shorts are the alphabetically first three
    assert shorts == set(sorted(SYMBOLS)[:3])
    assert result["episodes"] == 2 * 3 * 2  # two rebalances (index 0 and 7)


def test_price_jump_hits_long_side_with_target_weight() -> None:
    jumper = sorted(SYMBOLS)[-1]  # guaranteed long side under ascending tie-break
    data = synthetic_data(days=6, jump_symbol=jumper, jump=0.10)
    config = {"lookback_days": 1, "k_per_side": 3, "rebal_days": 7}
    result = simulate(config, data, PRIMARY_TRADE_COST)
    weight = 1.0 / 6.0
    # day 2 return reflects the long-side weight on the jumped symbol
    assert result["daily_returns"][1] == pytest.approx(weight * 0.10)
    # single rebalance (entry) inside the six-day window: exact closed form
    assert result["net_equity"] == pytest.approx((1.0 - PRIMARY_TRADE_COST) * (1.0 + weight * 0.10))
    assert result["episodes"] == 6


def test_funding_flips_transfer_to_short_side() -> None:
    rate = 0.001
    data = synthetic_data(days=9, rate=rate)
    config = {"lookback_days": 1, "k_per_side": 2, "rebal_days": 7}
    base = simulate(config, data, PRIMARY_TRADE_COST)
    flipped = simulate(config, data, PRIMARY_TRADE_COST, stress_funding="flipped")
    # neutral portfolio: symmetric funding cancels either way
    assert base["net_equity"] == pytest.approx(flipped["net_equity"])
    assert base["net_equity"] == pytest.approx(1.0 - PRIMARY_TRADE_COST)


def test_stress_costs_reduce_equity_monotonically() -> None:
    data = synthetic_data(days=9, rate=0.0005)
    config = {"lookback_days": 3, "k_per_side": 2, "rebal_days": 7}
    values = [simulate(config, data, c)["net_equity"] for c in
              (PRIMARY_TRADE_COST, *STRESS_TRADE_COSTS.values())]
    assert values == sorted(values, reverse=True)


def test_determinism_same_inputs_same_outputs() -> None:
    data = synthetic_data(days=30, rate=0.0007)
    config = {"lookback_days": 7, "k_per_side": 3, "rebal_days": 1}
    a = simulate(config, data, PRIMARY_TRADE_COST)
    b = simulate(config, data, PRIMARY_TRADE_COST)
    assert a["daily_returns"] == b["daily_returns"]
    assert a["net_equity"] == b["net_equity"]
    assert a["symbol_pnl"] == b["symbol_pnl"]


# ---------------------------------------------------------------------------
# metrics / eligibility


def test_max_drawdown_from_returns() -> None:
    assert max_drawdown_from_returns([0.1, -0.2]) == pytest.approx(-0.2)
    assert max_drawdown_from_returns([0.5, -0.5]) == pytest.approx(-0.5)
    assert max_drawdown_from_returns([0.01, 0.01]) == pytest.approx(0.0)


def test_fold_positions_cover_window_contiguously() -> None:
    total_days = (DECIDE_END_EXCLUSIVE_MS - DECIDE_START_MS) // DAY_MS
    assert FOLD_POSITIONS[0][0] == 0
    assert FOLD_POSITIONS[-1][1] == total_days
    for (_, end), (start, _) in zip(FOLD_POSITIONS, FOLD_POSITIONS[1:]):
        assert end == start


def test_config_metrics_shape_on_synthetic_run() -> None:
    total_window_days = (DECIDE_END_EXCLUSIVE_MS - DECIDE_START_MS) // DAY_MS
    data = synthetic_data(days=40, rate=0.0004)
    config = {"lookback_days": 1, "k_per_side": 2, "rebal_days": 7}
    key = config_key(config)
    metrics = config_metrics(key, config, simulate(config, data, PRIMARY_TRADE_COST))
    assert metrics["key"] == key
    assert len(metrics["daily_returns"]) == total_window_days
    assert len(metrics["fold_sharpes"]) == 11
    # rebalances at indices 0,7,14,21,28,35 of the populated prefix
    assert metrics["episodes"] == 4 * 6
    assert metrics["active_assets"] == 4
    assert isinstance(metrics["max_drawdown"], float)


def test_eligibility_thresholds() -> None:
    good = {
        "valid": True, "episodes": 200, "net_return": 0.05, "annualized_sharpe": 1.0,
        "max_drawdown": -0.1, "active_assets": 8, "max_asset_positive_share": 0.3,
    }
    assert is_eligible(good)
    assert not is_eligible({**good, "net_return": -0.01})
    assert not is_eligible({**good, "annualized_sharpe": 0.4})
    assert not is_eligible({**good, "max_drawdown": -0.3})
    assert not is_eligible({**good, "episodes": 99})
    assert not is_eligible({**good, "active_assets": 5})
    assert not is_eligible({**good, "max_asset_positive_share": 0.5})


# ---------------------------------------------------------------------------
# neighbor topology


def test_neighbors_exactly_four_symmetric() -> None:
    grid = frozen_grid()
    keys = {config_key(c) for c in grid}
    for config in grid:
        neighbors = neighbor_keys(config)
        assert len(neighbors) == 4
        for variant in neighbors:
            assert config_key(variant) in keys
            back = neighbor_keys(variant)
            assert config in back or config_key(config) in {config_key(v) for v in back}


def test_neighbor_profitability_gate() -> None:
    grid = frozen_grid()
    target = next(c for c in grid if c["lookback_days"] == 1 and c["k_per_side"] == 2 and c["rebal_days"] == 1)
    metrics_by_key = {}
    neighbors = neighbor_keys(target)
    for position, variant in enumerate(neighbors):
        metrics_by_key[config_key(variant)] = {
            "valid": True,
            "net_return": -0.01 if position == 0 else 0.02,
        }
    report = neighbor_profitability(target, metrics_by_key)
    assert report["neighbors_evaluated_valid"] == 4
    assert report["neighbors_profitable"] == 3
    assert report["gate_pass"] is True


# ---------------------------------------------------------------------------
# plumbing


def test_heritage_counts_include_all_published_and_current_configs() -> None:
    report = carry.heritage_sharpe_variance([0.05] * 12)
    assert report["counts"] == {"005": 5832, "006": 192, "007": 8}
    assert report["n"] == carry.HERITAGE_TRIALS == 6044
    assert report["variance"] >= 0.0


def test_run_sweep_rejects_foreign_checkpoint(tmp_path) -> None:
    checkpoint = tmp_path / "checkpoint-carry-001.json"
    checkpoint.write_text(json.dumps({"schema": "other", "seed": 1, "grid_count": 1, "rows": {}}))
    with pytest.raises(CarryError, match="resume rejected"):
        run_sweep(Path("nonexistent-root"), tmp_path)


def test_run_sweep_rejects_wrong_window_checkpoint(tmp_path) -> None:
    checkpoint = tmp_path / "checkpoint-carry-001.json"
    checkpoint.write_text(json.dumps({
        "schema": carry.SWEEP_SCHEMA, "seed": carry.SEED_SWEEP, "grid_count": 12,
        "window": [1, 2], "rows": {},
    }))
    with pytest.raises(CarryError, match="resume rejected"):
        run_sweep(Path("nonexistent-root"), tmp_path)


def test_missing_series_raises(tmp_path) -> None:
    with pytest.raises(CarryError, match="missing normalized series"):
        carry._read_daily_closes(tmp_path / "nope.csv.gz", DECIDE_END_EXCLUSIVE_MS)
