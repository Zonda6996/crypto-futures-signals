"""ALTCOIN_XS_001 tests: grid, momentum ranking, funding, plumbing."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.altcoin_carry_001 import CarryData
from research.altcoin_xs_001 import (
    DECIDE_END_EXCLUSIVE_MS,
    DECIDE_START_MS,
    DAY_MS,
    EXPECTED_GRID_COUNT,
    HERITAGE_TRIALS,
    K_PER_SIDE,
    WINDOWS,
    XsError,
    config_key,
    frozen_grid,
    heritage_sharpe_variance_xs,
    main,
    neighbor_keys,
    neighbor_profitability,
    run_sweep,
    simulate_xs,
)
import research.altcoin_xs_001 as xs

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
           "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT")
SORTED_SYMBOLS = tuple(sorted(SYMBOLS))


def make_data(days: int = 80, overrides: dict | None = None) -> CarryData:
    overrides = overrides or {}
    closes, funding, counts, firsts = {}, {}, {}, {}
    for symbol in SORTED_SYMBOLS:
        series = {DECIDE_START_MS + (t - 60) * DAY_MS: 100.0 * (1 + (0.001 if t % 2 else -0.001))
                  for t in range(-60, days)}
        for t, price in overrides.get(symbol, {}).items():
            series[DECIDE_START_MS + (t - 60) * DAY_MS] = price
        closes[symbol] = series
        funding[symbol] = {DECIDE_START_MS + t * DAY_MS: 0.0005 for t in range(days)}
        counts[symbol] = {DECIDE_START_MS + t * DAY_MS: 3 for t in range(days)}
        firsts[symbol] = DECIDE_START_MS - 60 * DAY_MS
    return CarryData(closes, funding, counts, firsts)


def test_grid_shape() -> None:
    grid = frozen_grid()
    assert len(grid) == EXPECTED_GRID_COUNT == 12
    combos = {(c["window_days"], c["k_per_side"], c["rebal_days"]) for c in grid}
    assert len(combos) == 12
    assert {c["window_days"] for c in grid} == set(WINDOWS) == {3, 7, 14}
    assert {c["k_per_side"] for c in grid} == set(K_PER_SIDE) == {2, 3}
    for c in grid:
        assert config_key(c) in {config_key(x) for x in frozen_grid()}


def test_validate_grid_cli(capsys) -> None:
    assert main(["--validate-grid"]) == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["count"] == 12
    assert payload["seed"] == 20261019


def test_momentum_ranks_riser_long_dumper_short() -> None:
    days = 80
    window = 14
    overrides = {}
    riser = "SOLUSDT"
    dumper = "XRPUSDT"
    price = 100.0
    for t in range(days - window, days):
        price *= 1.03
        overrides.setdefault(riser, {})[t] = price
    price = 100.0
    for t in range(days - window, days):
        price *= 0.97
        overrides.setdefault(dumper, {})[t] = price
    data = make_data(days, overrides)
    config = {"window_days": window, "k_per_side": 2, "rebal_days": 1}
    result = simulate_xs(config, data, 6e-4)
    assert result["valid"]
    fr = result["final_fractions"]
    assert fr[riser] > 0, "riser must be on the long side"
    assert fr[dumper] < 0, "dumper must be on the short side"
    assert abs(fr[riser]) == pytest.approx(0.25)
    assert sum(abs(v) for v in fr.values()) == pytest.approx(1.0)


def test_uniform_funding_cancels_on_neutral_book() -> None:
    data = make_data(30)
    config = {"window_days": 3, "k_per_side": 2, "rebal_days": 7}
    result = simulate_xs(config, data, 6e-4)
    assert result["valid"]
    # flat wiggle market: identical momenta -> alphabetical longs/shorts cancel
    assert result["net_equity"] == pytest.approx(1.0, rel=1e-9)


def test_funding_flip_stress_changes_pnl_only_for_held_book() -> None:
    data = make_data(30)
    config = {"window_days": 3, "k_per_side": 2, "rebal_days": 7}
    base = simulate_xs(config, data, 6e-4)
    flipped = simulate_xs(config, data, 6e-4, stress_funding="flipped")
    # symmetric book: flipped funding cancels identically -> same equity
    assert base["net_equity"] == pytest.approx(flipped["net_equity"])


def test_neighbors_four_and_symmetric() -> None:
    grid = frozen_grid()
    keys = {config_key(c) for c in grid}
    for config in grid:
        nks = neighbor_keys(config)
        assert len(nks) == 4
        for nk in nks:
            assert nk in keys
            assert config_key(config) in neighbor_keys(next(c for c in grid if config_key(c) == nk))


def test_neighbor_profitability_gate() -> None:
    target = next(c for c in frozen_grid() if c["window_days"] == 3 and c["k_per_side"] == 2 and c["rebal_days"] == 1)
    rows = {}
    for position, nk in enumerate(neighbor_keys(target)):
        rows[nk] = {"valid": True, "net_return": -0.01 if position == 0 else 0.05}
    report = neighbor_profitability(target, rows)
    assert report["neighbors_evaluated_valid"] == 4
    assert report["profitable_share"] == pytest.approx(0.75)
    assert report["gate_pass"] is True


def test_heritage_union_includes_mrtf001() -> None:
    report = heritage_sharpe_variance_xs([0.1] * 12)
    assert report["counts"] == {
        "005": 5832, "006": 192, "007": 8,
        "CARRY-001": 11, "RM-001": 8, "SL-001": 30, "FINAL-001": 8, "MR-TF-001": 32,
    }
    assert HERITAGE_TRIALS == 6_134
    assert report["n"] == 5832 + 192 + 8 + 11 + 8 + 30 + 8 + 32 + 12


def test_run_sweep_rejects_foreign_checkpoint(tmp_path) -> None:
    checkpoint = tmp_path / "checkpoint-xs-001.json"
    checkpoint.write_text(json.dumps({"schema": "other", "seed": 1, "grid_count": 1, "rows": {}}))
    with pytest.raises(XsError, match="resume rejected"):
        run_sweep(Path("nonexistent-root"), tmp_path)


def test_run_sweep_rejects_wrong_window_checkpoint(tmp_path) -> None:
    checkpoint = tmp_path / "checkpoint-xs-001.json"
    checkpoint.write_text(json.dumps({
        "schema": xs.SWEEP_SCHEMA, "seed": xs.SEED_SWEEP, "grid_count": 12,
        "window": [1, 2], "rows": {},
    }))
    with pytest.raises(XsError, match="resume rejected"):
        run_sweep(Path("nonexistent-root"), tmp_path)
