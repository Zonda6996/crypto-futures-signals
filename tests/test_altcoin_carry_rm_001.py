"""ALTCOIN_CARRY_RM_001 tests: overlay math, causality, invariants, plumbing.

All tests use synthetic data or committed repository artifacts only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.altcoin_carry_001 import CarryData, simulate as carry_simulate
from research.altcoin_carry_rm_001 import (
    CORES,
    DD_STARTS,
    DD_STOPS,
    DECIDE_END_EXCLUSIVE_MS,
    DECIDE_START_MS,
    DAY_MS,
    EXPECTED_GRID_COUNT,
    HERITAGE_TRIALS,
    ITEMS_BY_KEY,
    CarryError,
    exposure_multiplier,
    frozen_grid,
    heritage_sharpe_variance_rm,
    main,
    neighbor_keys,
    neighbor_profitability,
    run_sweep,
    simulate_rm,
)
import research.altcoin_carry_rm_001 as rm

SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
)


def synthetic_data(days: int, crashes: dict[int, float] | None = None, crash_symbol: str | None = None) -> CarryData:
    """Flat universe; optional stepped price shocks on one symbol (long side under ties)."""
    crashes = crashes or {}
    if crash_symbol is None:
        crash_symbol = sorted(SYMBOLS)[-1]
    start = DECIDE_START_MS
    closes, funding, counts, firsts = {}, {}, {}, {}
    for symbol in SYMBOLS:
        series = {start + t * DAY_MS - DAY_MS: 100.0 for t in range(days + 1)}
        level = 1.0
        for t in range(days):
            day = start + t * DAY_MS
            if symbol == crash_symbol and t in crashes:
                level *= 1.0 + crashes[t]
            series[day] = 100.0 * level
        series[start + days * DAY_MS] = 100.0 * level
        closes[symbol] = series
        funding[symbol] = {start + t * DAY_MS: 0.0005 for t in range(days)}
        counts[symbol] = {start + t * DAY_MS: 3 for t in range(days)}
        firsts[symbol] = start
    return CarryData(closes, funding, counts, firsts)


# ---------------------------------------------------------------------------
# grid


def test_grid_count_constraint_and_items_index() -> None:
    grid = frozen_grid()
    assert len(grid) == EXPECTED_GRID_COUNT == 8
    for item in grid:
        assert item["dd_start"] < item["dd_stop"]
        assert item["core"] in ("A", "B")
        key = rm._row_key(rm.CORES[item["core"]], item["dd_start"], item["dd_stop"])
        assert ITEMS_BY_KEY[key] == item
    combos = {(i["core"], i["dd_start"], i["dd_stop"]) for i in grid}
    assert len(combos) == 8
    assert {(c, s) for c in ("A", "B") for s in DD_STARTS} <= {(c, s) for c, s, _ in combos}


def test_validate_grid_cli(capsys) -> None:
    assert main(["--validate-grid"]) == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["count"] == 8
    assert payload["seed"] == 20260921


# ---------------------------------------------------------------------------
# overlay math


def test_exposure_multiplier_linear_map() -> None:
    assert exposure_multiplier(0.0, 0.05, 0.15) == 1.0          # no drawdown
    assert exposure_multiplier(-0.05, 0.05, 0.15) == 1.0        # exactly at start
    assert exposure_multiplier(-0.10, 0.05, 0.15) == pytest.approx(0.5)  # midpoint
    assert exposure_multiplier(-0.15, 0.05, 0.15) == 0.0        # fully flat at stop
    assert exposure_multiplier(-0.50, 0.05, 0.15) == 0.0        # beyond stop stays flat
    assert exposure_multiplier(-0.125, 0.05, 0.20) == pytest.approx(0.5)
    assert exposure_multiplier(-0.02, 0.05, 0.20) == 1.0        # shallower than start


def test_overlay_caps_exposure_after_deep_crash() -> None:
    # two crash days in a row: the first builds drawdown past dd_start, so the
    # overlay must shrink exposure before the second hit and soften the worst day.
    data = synthetic_data(days=12, crashes={5: -0.35, 6: -0.45})
    core = CORES["A"]
    managed = simulate_rm(core, 0.05, 0.15, data, 6e-4)
    bare = simulate_rm(core, 1.0, 2.0, data, 6e-4, use_overlay=False)
    gross_final = sum(abs(v) for v in managed["final_fractions"].values())
    assert gross_final <= 1.0 + 1e-9
    assert managed["valid"]
    assert min(managed["daily_returns"][1:]) > min(bare["daily_returns"][1:])


# ---------------------------------------------------------------------------
# invariant: overlay disabled reproduces the bare CARRY-001 simulator


@pytest.mark.parametrize("core", [CORES["A"], CORES["B"]])
def test_no_overlay_matches_carry001_simulator(core) -> None:
    data = synthetic_data(days=40, crashes={5: -0.25})
    bare = simulate_rm(core, 1.0, 2.0, data, 6e-4, use_overlay=False)
    reference = carry_simulate(core, data, 6e-4)
    assert bare["daily_returns"] == reference["daily_returns"]
    assert bare["net_equity"] == pytest.approx(reference["net_equity"])
    assert bare["episodes"] == reference["episodes"]


def test_overlay_reduces_worst_day_vs_bare_core() -> None:
    data = synthetic_data(days=40, crashes={10: -0.30, 11: -0.40})
    core = CORES["B"]
    bare = simulate_rm(core, 1.0, 2.0, data, 6e-4, use_overlay=False)
    managed = simulate_rm(core, 0.05, 0.15, data, 6e-4)
    worst_bare = min(bare["daily_returns"][1:])
    worst_managed = min(managed["daily_returns"][1:])
    assert worst_managed > worst_bare
    assert managed["net_equity"] != pytest.approx(bare["net_equity"])


# ---------------------------------------------------------------------------
# neighbors


def test_neighbors_exactly_three_and_symmetric() -> None:
    for key, item in ITEMS_BY_KEY.items():
        neighbors = neighbor_keys(item)
        assert len(neighbors) == 3
        for variant in neighbors:
            vkey = rm._row_key(rm.CORES[variant["core"]], variant["dd_start"], variant["dd_stop"])
            assert vkey in ITEMS_BY_KEY
            back = neighbor_keys(variant)
            assert any(
                rm._row_key(rm.CORES[b["core"]], b["dd_start"], b["dd_stop"]) == key for b in back
            )


def test_neighbor_profitability_gate_counts() -> None:
    target = next(i for i in ITEMS_BY_KEY.values() if i["core"] == "A" and i["dd_start"] == 0.05 and i["dd_stop"] == 0.15)
    rows = {}
    for position, variant in enumerate(neighbor_keys(target)):
        vkey = rm._row_key(rm.CORES[variant["core"]], variant["dd_start"], variant["dd_stop"])
        rows[vkey] = {"valid": True, "net_return": -0.01 if position == 0 else 0.05}
    report = neighbor_profitability(target, rows)
    assert report["neighbors_evaluated_valid"] == 3
    assert report["neighbors_profitable"] == 2
    assert report["gate_pass"] is True


# ---------------------------------------------------------------------------
# heritage


def test_heritage_union_includes_carry001_published_sharpes() -> None:
    report = heritage_sharpe_variance_rm([0.10] * 8)
    assert report["counts"] == {"005": 5832, "006": 192, "007": 8, "CARRY-001": 11}
    assert report["n"] == 5832 + 192 + 8 + 11 + 8
    assert HERITAGE_TRIALS == 6_052


# ---------------------------------------------------------------------------
# plumbing


def test_run_sweep_rejects_foreign_checkpoint(tmp_path) -> None:
    checkpoint = tmp_path / "checkpoint-carry-rm-001.json"
    checkpoint.write_text(json.dumps({"schema": "other", "seed": 1, "grid_count": 1, "rows": {}}))
    with pytest.raises(CarryError, match="resume rejected"):
        run_sweep(Path("nonexistent-root"), tmp_path)


def test_run_sweep_rejects_wrong_window_checkpoint(tmp_path) -> None:
    checkpoint = tmp_path / "checkpoint-carry-rm-001.json"
    checkpoint.write_text(json.dumps({
        "schema": rm.SWEEP_SCHEMA, "seed": rm.SEED_SWEEP, "grid_count": 8,
        "window": [1, 2], "rows": {},
    }))
    with pytest.raises(CarryError, match="resume rejected"):
        run_sweep(Path("nonexistent-root"), tmp_path)
