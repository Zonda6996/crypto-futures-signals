"""ALT-MULTITF-007 tests: frozen grid, calendar folds, neighbor topology, plumbing.

All tests use synthetic data or committed repository artifacts only; no external
market data is required.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from research.altcoin_multitf_gates import ConfigMetrics, compute_metrics
from research.altcoin_multitf_phase3 import ExchangeRules, Family
from research.altcoin_multitf_phase4 import Diagnostics as Phase4Diagnostics
from research.altcoin_multitf_phase4 import Evaluation, Trade
from research.altcoin_multitf_phase7 import (
    DECIDE_END_EXCLUSIVE_MS,
    DECIDE_START_MS,
    EXPECTED_GRID_COUNT,
    FOLD_BOUNDS_007,
    HALF_YEAR_BOUNDARIES_MS,
    Phase7Error,
    _metrics_from_row,
    _neighbors,
    frozen_grid_007,
    heritage_sharpe_variance,
    load_frozen_rules,
    main,
    run_sweep,
)
import research.altcoin_multitf_phase7 as phase7


DAY_MS = 86_400_000


# ---------------------------------------------------------------------------
# frozen grid


def test_frozen_grid_007_count_and_shape() -> None:
    grid = frozen_grid_007()
    assert len(grid) == EXPECTED_GRID_COUNT == 8
    keys = [c.key for c in grid]
    assert len(set(keys)) == len(keys)
    assert keys == sorted(keys)
    pairs = {(c.fast_window, c.slow_window) for c in grid}
    assert pairs == {(20, 100), (50, 200)}
    assert {c.entry_threshold for c in grid} == {0.005, 0.01}
    assert {c.max_holding_bars for c in grid} == {2880, 11520}
    for config in grid:
        assert config.family is Family.A
        assert config.signal_tf_minutes == 1440
        assert config.regime_tf_minutes == 10080
        assert config.exit_threshold == 0.0
        assert config.stop_atr == 3.0
        assert config.take_atr == 6.0
        assert config.side == "long"


def test_validate_grid_cli_reports_eight(tmp_path, capsys) -> None:
    assert main(["--validate-grid"]) == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["count"] == 8
    assert payload["seed"] == 20260907


# ---------------------------------------------------------------------------
# calendar half-year folds


def test_fold_bounds_007_are_eleven_calendar_half_years() -> None:
    assert len(FOLD_BOUNDS_007) == 11
    assert len(HALF_YEAR_BOUNDARIES_MS) == 12
    assert FOLD_BOUNDS_007[0][0] == DECIDE_START_MS
    assert FOLD_BOUNDS_007[-1][1] == DECIDE_END_EXCLUSIVE_MS
    for (_, end), (start, _) in zip(FOLD_BOUNDS_007, FOLD_BOUNDS_007[1:]):
        assert end == start
    labels = ("2021-01-01", "2021-07-01", "2022-01-01", "2022-07-01", "2023-01-01", "2023-07-01",
              "2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01", "2026-07-01")
    from datetime import datetime, timezone

    for boundary, label in zip(HALF_YEAR_BOUNDARIES_MS, labels):
        moment = datetime.fromtimestamp(boundary / 1000, tz=timezone.utc)
        assert moment.strftime("%Y-%m-%d") == label
        assert moment.hour == moment.minute == moment.second == 0


def _evaluation_with_trades(trades: list[Trade]) -> Evaluation:
    return Evaluation("k", True, tuple(trades), 100.0 + sum(t.net_pnl for t in trades), Phase4Diagnostics())


def _trade(entry_day: float, exit_day: float, net_pnl: float) -> Trade:
    return Trade(
        side=1,
        quantity=1.0,
        entry_time_ms=int(entry_day * DAY_MS),
        exit_time_ms=int(exit_day * DAY_MS),
        entry_price=100.0,
        exit_price=100.0 + net_pnl,
        gross_pnl=net_pnl,
        fees=0.0,
        slippage=0.0,
        funding=0.0,
        net_pnl=net_pnl,
        return_on_equity=net_pnl / 100.0,
        exit_reason="signal",
    )


def test_compute_metrics_calendar_override_attributes_by_exit() -> None:
    trades = [_trade(1.0, 1.5, 10.0), _trade(7.0, 9.0, -4.0)]
    evaluation = _evaluation_with_trades(trades)
    metrics = compute_metrics(
        "k",
        {"BTCUSDT": evaluation},
        initial_equity=100.0,
        window_start_ms=0,
        window_end_ms=10 * DAY_MS,
        fold_bounds_override=[(0, 8 * DAY_MS), (8 * DAY_MS, 10 * DAY_MS)],
    )
    assert metrics.valid
    assert metrics.trades == 2
    assert len(metrics.fold_net_returns) == 2
    assert metrics.fold_net_returns[0] == pytest.approx(0.10)
    assert metrics.fold_net_returns[1] == pytest.approx(-0.04)
    assert metrics.positive_folds == 1


def test_compute_metrics_default_even_split_unchanged() -> None:
    trades = [_trade(1.0, 1.5, 10.0)]
    evaluation = _evaluation_with_trades(trades)
    metrics = compute_metrics(
        "k",
        {"BTCUSDT": evaluation},
        initial_equity=100.0,
        window_start_ms=0,
        window_end_ms=6 * DAY_MS,
    )
    assert len(metrics.fold_sharpes) == 6
    assert len(metrics.daily_returns) == 6


def test_metrics_row_round_trip_preserves_fields() -> None:
    trades = [_trade(1.0, 1.5, 10.0)]
    evaluation = _evaluation_with_trades(trades)
    metrics = compute_metrics(
        "k",
        {"BTCUSDT": evaluation},
        initial_equity=100.0,
        window_start_ms=0,
        window_end_ms=10 * DAY_MS,
        fold_bounds_override=[(0, 8 * DAY_MS), (8 * DAY_MS, 10 * DAY_MS)],
    )
    from research.altcoin_multitf_phase7 import row_from_metrics

    row = row_from_metrics(metrics, frozen_grid_007()[0])
    restored = _metrics_from_row(row)
    assert restored.config_key == metrics.config_key
    assert restored.fold_net_returns == metrics.fold_net_returns
    assert restored.daily_returns == metrics.daily_returns
    assert restored.positive_folds == metrics.positive_folds


# ---------------------------------------------------------------------------
# neighbor topology: sma_pair | entry | holding


def test_neighbors_007_exactly_three_per_config_and_symmetric() -> None:
    grid = list(frozen_grid_007())
    neighbors = _neighbors(grid)
    for key, targets in neighbors.items():
        assert len(targets) == 3, (key, targets)
    for key, targets in neighbors.items():
        for other in targets:
            assert key in neighbors[other]


# ---------------------------------------------------------------------------
# heritage report inputs


def test_heritage_sharpe_variance_counts_all_published_configs() -> None:
    report = heritage_sharpe_variance([0.1, 0.3])
    assert report["counts"]["005"] == 5832
    assert report["counts"]["006"] == 192
    assert report["n"] == 5832 + 192 + 2
    assert math.isfinite(report["variance"])
    assert report["variance"] >= 0.0


# ---------------------------------------------------------------------------
# freeze-time rules and checkpoint identity


def test_load_frozen_rules_covers_universe() -> None:
    rules = load_frozen_rules()
    from research.altcoin_multitf_inputs import UNIVERSE_SYMBOLS

    assert set(rules) >= set(UNIVERSE_SYMBOLS)
    rule = rules["BTCUSDT"]
    assert isinstance(rule, ExchangeRules)
    assert rule.tick_size > 0 and rule.step_size > 0 and rule.min_notional > 0


def test_load_frozen_rules_rejects_hash_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(phase7, "sha256_file", lambda path: "0" * 64)
    with pytest.raises(Phase7Error, match="rules file hash mismatch"):
        load_frozen_rules()


def test_run_sweep_rejects_foreign_checkpoint(tmp_path) -> None:
    checkpoint = tmp_path / "checkpoint-007.json"
    checkpoint.write_text(json.dumps({"schema": "something-else", "seed": 1, "grid_count": 1, "rows": {}}))
    with pytest.raises(Phase7Error, match="resume rejected"):
        run_sweep(Path("nonexistent-root"), tmp_path)


def test_run_sweep_rejects_wrong_window_checkpoint(tmp_path) -> None:
    checkpoint = tmp_path / "checkpoint-007.json"
    checkpoint.write_text(json.dumps({
        "schema": phase7.SWEEP_SCHEMA, "seed": phase7.SEED_SWEEP, "grid_count": 8,
        "window": [123, 456], "rows": {},
    }))
    with pytest.raises(Phase7Error, match="resume rejected"):
        run_sweep(Path("nonexistent-root"), tmp_path)
