"""ALTCOIN_CARRY_FINAL_001 tests: grid, hedge math, weights, gate, invariants."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.altcoin_carry_001 import simulate as carry_simulate
from research.altcoin_carry_sl_001 import CORES, SlData, simulate_sl
from research.altcoin_carry_final_001 import (
    BETA_WINDOW,
    DECIDE_END_EXCLUSIVE_MS,
    DECIDE_START_MS,
    DAY_MS,
    EXPECTED_GRID_COUNT,
    HERITAGE_TRIALS,
    ITEMS_BY_KEY,
    FinalError,
    frozen_grid,
    gate_is_open,
    heritage_sharpe_variance_final,
    main,
    neighbor_items,
    neighbor_profitability,
    run_sweep,
    simulate_final,
    trailing_beta,
)
import research.altcoin_carry_final_001 as fin

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
           "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT")
SORTED_SYMBOLS = tuple(sorted(SYMBOLS))


def wiggle(days: int, amp: float = 0.005, base: float = 100.0) -> dict[int, list[float]]:
    out = {}
    start = DECIDE_START_MS
    for t in range(-41, days):
        day = start + t * DAY_MS
        c = base * (1 + (amp if t % 2 == 0 else -amp))
        out[day] = [c * (1 + amp), c * (1 - amp), c]
    return out


def make_data(days: int, overrides: dict | None = None, funding_pattern=None) -> SlData:
    from research.altcoin_carry_sl_001 import wilder_atr
    from research.altcoin_carry_001 import CarryData

    overrides = overrides or {}
    closes, highs, lows, funding, counts, firsts = {}, {}, {}, {}, {}, {}
    for symbol in SORTED_SYMBOLS:
        series = wiggle(days)
        for day_str, ohlc in overrides.get(symbol, {}).items():
            series[int(day_str)] = ohlc
        highs[symbol] = {d: v[0] for d, v in series.items()}
        lows[symbol] = {d: v[1] for d, v in series.items()}
        closes[symbol] = {d: v[2] for d, v in series.items()}
        funding[symbol] = {}
        counts[symbol] = {}
        for t in range(-400, days):
            day = DECIDE_START_MS + t * DAY_MS
            rate = funding_pattern(symbol, t) if funding_pattern else 0.0005
            funding[symbol][day] = rate
            counts[symbol][day] = 3
        firsts[symbol] = DECIDE_START_MS - 400 * DAY_MS - 41 * DAY_MS
    carry = CarryData(closes, funding, counts, firsts)
    atr = {s: wilder_atr(highs[s], lows[s], closes[s], 14) for s in SORTED_SYMBOLS}
    return SlData(carry, atr)


CHAMPION_SL_ITEM = next(
    i for i in
    __import__("research.altcoin_carry_sl_001", fromlist=["frozen_grid"]).frozen_grid()
    if i["core_name"] == "A" and i["stop_style"] == "atr3" and i["take_code"] == "f1:1"
)


# ---------------------------------------------------------------------------
# grid / CLI


def test_grid_shape_and_index() -> None:
    grid = frozen_grid()
    assert len(grid) == EXPECTED_GRID_COUNT == 8
    combos = {(i["hedge"], i["weights"], i["gate"]) for i in grid}
    assert len(combos) == 8
    assert (False, "equal", "always") in combos  # champion corner present
    for item in grid:
        assert ITEMS_BY_KEY[item["key"]] == item


def test_validate_grid_cli(capsys) -> None:
    assert main(["--validate-grid"]) == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["count"] == 8
    assert payload["seed"] == 20261005


# ---------------------------------------------------------------------------
# champion-corner invariant


def test_all_off_corner_reproduces_sl001_champion_exactly() -> None:
    data = make_data(40)
    corner = ITEMS_BY_KEY[fin.item_key(False, "equal", "always")]
    ours = simulate_final(corner, data, 6e-4)
    reference = simulate_sl(CHAMPION_SL_ITEM, data, 6e-4)
    assert ours["daily_returns"] == reference["daily_returns"]
    assert ours["net_equity"] == pytest.approx(reference["net_equity"])
    assert ours["episodes"] == reference["episodes"]


# ---------------------------------------------------------------------------
# hedge


def test_trailing_beta_identity_on_identical_series() -> None:
    data = make_data(60)
    # every symbol follows the same wiggle as BTC -> beta exactly 1
    assert trailing_beta(data, "SOLUSDT", DECIDE_START_MS + 50 * DAY_MS) == pytest.approx(1.0)


def test_trailing_beta_hand_computed() -> None:
    days = BETA_WINDOW + 5
    overrides = {}
    # SOL: amplified wiggle (2x) -> beta exactly 2 against the base wiggle
    for t in range(-41, days):
        day = DECIDE_START_MS + t * DAY_MS
        base_c = 100.0 * (1 + (0.005 if t % 2 == 0 else -0.005))
        sol_c = 100.0 * (1 + (0.010 if t % 2 == 0 else -0.010))
        overrides[str(day)] = [sol_c * 1.002, sol_c * 0.998, sol_c]
    data = make_data(days, overrides={"SOLUSDT": overrides})
    beta = trailing_beta(data, "SOLUSDT", DECIDE_START_MS + (days - 1) * DAY_MS)
    assert beta == pytest.approx(2.0, rel=1e-3)


def test_hedge_shorts_btc_when_book_beta_positive() -> None:
    days = 95  # enough pre-window history for the 90-day beta estimation
    overrides = {}
    # SOL (long side under ties) carries double beta -> book net beta positive
    for t in range(-41, days):
        day = DECIDE_START_MS + t * DAY_MS
        base_c = 100.0 * (1 + (0.005 if t % 2 == 0 else -0.005))
        sol_c = 100.0 * (1 + (0.010 if t % 2 == 0 else -0.010))
        overrides[str(day)] = [sol_c * 1.002, sol_c * 0.998, sol_c]
    data = make_data(days, overrides={"SOLUSDT": overrides})
    item = dict(ITEMS_BY_KEY[fin.item_key(True, "equal", "always")])
    result = simulate_final(item, data, 6e-4)
    assert result["valid"]
    # longs {LINK, SOL, XRP} at +1/6 each; SOL beta 2, others 1;
    # shorts {ADA, AVAX, BNB} at -1/6, beta 1 -> beta_book = +1/6 -> hedge -1/6
    assert result["final_hedge"] == pytest.approx(-1.0 / 6.0, rel=1e-3)
    flat = simulate_final(ITEMS_BY_KEY[fin.item_key(False, "equal", "always")], data, 6e-4)
    assert flat["net_equity"] != pytest.approx(result["net_equity"])
    # dollar-neutral book with uniform betas carries zero net beta -> no hedge
    plain = make_data(40)
    assert simulate_final(item, plain, 6e-4)["final_hedge"] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# weights


def test_invvol_weights_preserve_gross_and_scale_by_sigma() -> None:
    days = 40
    overrides = {}
    for t in range(-41, days):
        day = DECIDE_START_MS + t * DAY_MS
        base_c = 100.0 * (1 + (0.005 if t % 2 == 0 else -0.005))
        xrp_c = 100.0 * (1 + (0.015 if t % 2 == 0 else -0.015))
        overrides[str(day)] = [xrp_c * 1.002, xrp_c * 0.998, xrp_c]
    data = make_data(days, overrides={"XRPUSDT": overrides})
    item = dict(ITEMS_BY_KEY[fin.item_key(False, "invvol", "always")])
    result = simulate_final(item, data, 6e-4)
    fr = result["final_fractions"]
    longs = {s: fr[s] for s in ("SOLUSDT", "XRPUSDT")}
    # XRP sigma = 3x SOL sigma -> weight ratio 3:1, book gross preserved at 1.0
    assert longs["SOLUSDT"] / longs["XRPUSDT"] == pytest.approx(3.0, rel=1e-3)
    assert sum(abs(v) for v in fr.values()) == pytest.approx(1.0)


def test_invvol_differs_from_equal_but_corner_matches() -> None:
    data = make_data(40)
    equal = simulate_final(ITEMS_BY_KEY[fin.item_key(False, "equal", "always")], data, 6e-4)
    invvol = simulate_final(ITEMS_BY_KEY[fin.item_key(False, "invvol", "always")], data, 6e-4)
    # identical wiggle everywhere -> sigma equal -> weights equal -> same path
    assert invvol["daily_returns"] == equal["daily_returns"]


# ---------------------------------------------------------------------------
# gate


def test_gate_is_open_pure_logic() -> None:
    disp = {DECIDE_START_MS + i * DAY_MS: 1.0 for i in range(200)}
    today = DECIDE_START_MS + 200 * DAY_MS
    assert gate_is_open(disp, today) is True          # current == median -> open
    disp[today] = 0.5
    assert gate_is_open(disp, today) is False          # below trailing median
    disp[today] = 2.0
    assert gate_is_open(disp, today) is True           # above median
    short = {DECIDE_START_MS + i * DAY_MS: 1.0 for i in range(10)}
    assert gate_is_open(short, DECIDE_START_MS + 10 * DAY_MS) is True  # short history -> open


def test_dispersion_gate_blocks_opens_in_flat_regime() -> None:
    def pattern(symbol, t):
        if t < 15:
            return 0.0005 * (1 + SORTED_SYMBOLS.index(symbol))  # dispersed
        return 0.0005  # converged: zero dispersion
    crash_day = 25
    overrides = {"SOLUSDT": {str(DECIDE_START_MS + crash_day * DAY_MS): [91.0, 89.5, 90.0]}}
    data = make_data(40, overrides=overrides, funding_pattern=pattern)
    gated = simulate_final(ITEMS_BY_KEY[fin.item_key(False, "equal", "dispersion")], data, 6e-4)
    always = simulate_final(ITEMS_BY_KEY[fin.item_key(False, "equal", "always")], data, 6e-4)
    assert gated["valid"] and always["valid"]
    # after the crash the stopped long re-opens only in the ungated config
    assert gated["episodes"] < always["episodes"]


# ---------------------------------------------------------------------------
# neighbours / heritage / plumbing


def test_neighbors_exactly_three_symmetric() -> None:
    for key, item in ITEMS_BY_KEY.items():
        neighbors = neighbor_items(item)
        assert len(neighbors) == 3
        for variant in neighbors:
            assert variant["key"] in ITEMS_BY_KEY
            back = neighbor_items(variant)
            assert any(b["key"] == key for b in back)


def test_neighbor_profitability_gate() -> None:
    target = ITEMS_BY_KEY[fin.item_key(False, "equal", "always")]
    rows = {}
    for position, variant in enumerate(neighbor_items(target)):
        rows[variant["key"]] = {"valid": True, "net_return": -0.01 if position == 0 else 0.05}
    report = neighbor_profitability(target, rows)
    assert report["neighbors_evaluated_valid"] == 3
    assert report["gate_pass"] is True


def test_heritage_union_includes_sl001() -> None:
    report = heritage_sharpe_variance_final([0.1] * 8)
    assert report["counts"] == {
        "005": 5832, "006": 192, "007": 8, "CARRY-001": 11, "RM-001": 8, "SL-001": 30,
    }
    assert report["n"] == 5832 + 192 + 8 + 11 + 8 + 30 + 8
    assert HERITAGE_TRIALS == 6_090


def test_run_sweep_rejects_foreign_checkpoint(tmp_path) -> None:
    checkpoint = tmp_path / "checkpoint-carry-final-001.json"
    checkpoint.write_text(json.dumps({"schema": "other", "seed": 1, "grid_count": 1, "rows": {}}))
    with pytest.raises(FinalError, match="resume rejected"):
        run_sweep(Path("nonexistent-root"), tmp_path)


def test_run_sweep_rejects_wrong_window_checkpoint(tmp_path) -> None:
    checkpoint = tmp_path / "checkpoint-carry-final-001.json"
    checkpoint.write_text(json.dumps({
        "schema": fin.SWEEP_SCHEMA, "seed": fin.SEED_SWEEP, "grid_count": 8,
        "window": [1, 2], "rows": {},
    }))
    with pytest.raises(FinalError, match="resume rejected"):
        run_sweep(Path("nonexistent-root"), tmp_path)
