"""ALTCOIN_MR_TF_001 tests: grid, trigger, exits, funding sign, plumbing."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.altcoin_mr_tf_001 import (
    DECIDE_END_EXCLUSIVE_MS,
    DECIDE_START_MS,
    DAY_MS,
    EXPECTED_GRID_COUNT,
    HERITAGE_TRIALS,
    HOLD_BARS,
    ITEMS_BY_KEY,
    MrData,
    MrError,
    TfSeries,
    frozen_grid,
    generate_trades,
    heritage_sharpe_variance_mr,
    item_key,
    main,
    neighbor_keys,
    neighbor_profitability,
    run_sweep,
)
import research.altcoin_mr_tf_001 as mr

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
           "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT")
SORTED_SYMBOLS = tuple(sorted(SYMBOLS))


def series_from_closes(closes_by_index: dict[int, float], amp: float = 0.001, n: int = 120) -> TfSeries:
    opens = [DECIDE_START_MS + (i - 60) * DAY_MS for i in range(n)]
    closes = []
    highs = []
    lows = []
    for i in range(n):
        if i in closes_by_index:
            c = closes_by_index[i]
        else:
            c = 100.0 * (1 + (amp if i % 2 == 0 else -amp))
        closes.append(c)
        highs.append(c * 1.002)
        lows.append(c * 0.998)
    return TfSeries(opens, closes, highs, lows)


def make_data(closes_by_index: dict[int, float] | None = None, symbol_overrides: dict | None = None,
              funding: tuple | None = None) -> MrData:
    closes_by_index = closes_by_index or {}
    symbol_overrides = symbol_overrides or {}
    series = {}
    for symbol in SORTED_SYMBOLS:
        base = series_from_closes(closes_by_index)
        if symbol in symbol_overrides:
            base = series_from_closes(symbol_overrides[symbol])
        series[symbol] = {tf: base for tf in ("1d", "2h", "4h", "1h")}
    f = funding or ((), ())
    return MrData(series, {s: f for s in SORTED_SYMBOLS})


# ---------------------------------------------------------------------------
# grid / CLI


def test_grid_shape() -> None:
    grid = frozen_grid()
    assert len(grid) == EXPECTED_GRID_COUNT == 32
    combos = {(i["tf"], i["z"], i["side"], i["exit"]) for i in grid}
    assert len(combos) == 32
    assert {i["tf"] for i in grid} == {"1d", "2h", "4h", "1h"}
    for item in grid:
        assert ITEMS_BY_KEY[item["key"]] == item


def test_hold_bars_are_three_days() -> None:
    assert HOLD_BARS == {"1d": 3, "2h": 36, "4h": 18, "1h": 72}


def test_validate_grid_cli(capsys) -> None:
    assert main(["--validate-grid"]) == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["count"] == 32
    assert payload["seed"] == 20261012


# ---------------------------------------------------------------------------
# trigger / exits


def test_long_signal_after_sharp_drop_time3_exit() -> None:
    drop_i = 70
    data = make_data({drop_i: 90.0})
    item = {"key": "t", "tf": "1d", "z": 2.0, "side": "long", "exit": "time3"}
    trades = generate_trades(item, data, 0.0012)
    sol = trades["SOLUSDT"]
    assert len(sol) == 1
    t = sol[0]
    assert t.side == 1
    assert t.entry_price == pytest.approx(90.0)
    assert t.exit_time_ms - t.entry_time_ms == 3 * DAY_MS
    # net includes 12 bps round trip; price move +11.1% compounding from 90->~100.4
    assert t.net_pnl > 0


def test_tp11_stop_fires() -> None:
    drop_i = 70
    closes = {drop_i: 90.0, drop_i + 1: 84.0}  # ATR~0.3 -> stop dist 2*ATR << drop
    data = make_data(closes)
    item = {"key": "t", "tf": "1d", "z": 2.0, "side": "long", "exit": "tp11"}
    trades = generate_trades(item, data, 0.0012)
    sol = trades["SOLUSDT"]
    assert len(sol) == 1
    assert sol[0].exit_reason == "stop"
    assert sol[0].exit_time_ms - sol[0].entry_time_ms == 1 * DAY_MS


def test_tp11_take_fires_on_rebound() -> None:
    drop_i = 70
    closes = {drop_i: 90.0, drop_i + 1: 97.0}  # +7.8% > 2*ATR take
    data = make_data(closes)
    item = {"key": "t", "tf": "1d", "z": 2.0, "side": "long", "exit": "tp11"}
    trades = generate_trades(item, data, 0.0012)
    sol = trades["SOLUSDT"]
    assert len(sol) == 1
    assert sol[0].exit_reason == "take"
    assert sol[0].net_pnl > 0


def test_short_after_pump_in_both_mode() -> None:
    pump_i = 70
    data = make_data({pump_i: 115.0})
    item = {"key": "t", "tf": "1d", "z": 2.0, "side": "both", "exit": "time3"}
    trades = generate_trades(item, data, 0.0012)
    sol = trades["SOLUSDT"]
    assert len(sol) == 1
    assert sol[0].side == -1


def test_long_only_ignores_pumps() -> None:
    pump_i = 70
    data = make_data({pump_i: 115.0})
    item = {"key": "t", "tf": "1d", "z": 2.0, "side": "long", "exit": "time3"}
    trades = generate_trades(item, data, 0.0012)
    sol = trades["SOLUSDT"]
    # the pump bar itself never triggers a short in long-only mode; any trade
    # that appears can only be the long on the reversal bar after the pump
    assert all(t.side == 1 for t in sol)


def test_one_trade_per_symbol_and_funding_sign() -> None:
    # two consecutive crash bars: second signal must be skipped while in trade
    data = make_data({70: 90.0, 71: 85.0}, funding=([DECIDE_START_MS + 11 * DAY_MS], [0.001]))
    item = {"key": "t", "tf": "1d", "z": 2.0, "side": "long", "exit": "time3"}
    trades = generate_trades(item, data, 0.0012)
    sol = trades["SOLUSDT"]
    assert len(sol) == 1
    t = sol[0]
    # long pays positive funding: net = price_pnl - cost - funding
    price_pnl = (t.exit_price - t.entry_price) / t.entry_price
    expected = (price_pnl - 0.0012 - 0.001) * 10_000
    assert t.net_pnl == pytest.approx(expected, rel=1e-6)


def test_flat_market_no_trades() -> None:
    data = make_data()
    item = {"key": "t", "tf": "1d", "z": 2.0, "side": "both", "exit": "time3"}
    trades = generate_trades(item, data, 0.0012)
    assert all(v == [] for v in trades.values())


# ---------------------------------------------------------------------------
# neighbours / heritage / plumbing


def test_neighbors_six_and_symmetric() -> None:
    for key in ITEMS_BY_KEY:
        item = ITEMS_BY_KEY[key]
        nks = neighbor_keys(item)
        assert len(nks) == 6
        for nk in nks:
            assert nk in ITEMS_BY_KEY
            assert key in neighbor_keys(ITEMS_BY_KEY[nk])


def test_neighbor_profitability_gate() -> None:
    target = ITEMS_BY_KEY[item_key("1d", 2.0, "long", "time3")]
    rows = {}
    for position, nk in enumerate(neighbor_keys(target)):
        rows[nk] = {"valid": True, "net_return": -0.01 if position < 2 else 0.05}
    report = neighbor_profitability(target, rows)
    assert report["neighbors_evaluated_valid"] == 6
    assert report["profitable_share"] == pytest.approx(4 / 6)
    assert report["gate_pass"] is True


def test_heritage_union_includes_final001() -> None:
    report = heritage_sharpe_variance_mr([0.1] * 32)
    assert report["counts"] == {
        "005": 5832, "006": 192, "007": 8,
        "CARRY-001": 11, "RM-001": 8, "SL-001": 30, "FINAL-001": 8,
    }
    assert HERITAGE_TRIALS == 6_122
    assert report["n"] == 5832 + 192 + 8 + 11 + 8 + 30 + 8 + 32


def test_run_sweep_rejects_foreign_checkpoint(tmp_path) -> None:
    checkpoint = tmp_path / "checkpoint-mr-tf-001.json"
    checkpoint.write_text(json.dumps({"schema": "other", "seed": 1, "grid_count": 1, "rows": {}}))
    with pytest.raises(MrError, match="resume rejected"):
        run_sweep(Path("nonexistent-root"), tmp_path)


def test_run_sweep_rejects_wrong_window_checkpoint(tmp_path) -> None:
    checkpoint = tmp_path / "checkpoint-mr-tf-001.json"
    checkpoint.write_text(json.dumps({
        "schema": mr.SWEEP_SCHEMA, "seed": mr.SEED_SWEEP, "grid_count": 32,
        "window": [1, 2], "rows": {},
    }))
    with pytest.raises(MrError, match="resume rejected"):
        run_sweep(Path("nonexistent-root"), tmp_path)
