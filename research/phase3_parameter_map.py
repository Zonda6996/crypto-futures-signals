from __future__ import annotations

import csv
import json
from dataclasses import asdict
from itertools import product
from pathlib import Path
from statistics import median
from typing import Sequence

from .core import Bar, assert_selection_indices, chronological_splits
from .data import download_symbol
from .features import make_features
from .phase1_audit import COST_SCENARIOS, YEARS
from .phase2_walk_forward import aggregate_rows
from .search import Candidate, calibrate_candidate, evaluate_candidate

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "reports" / "phase3"
VWAP_HOURS = (12, 24, 48, 72)
STOP_ATR = (1.2, 1.5, 1.8, 2.0)
TAKE_ATR = (1.5, 2.0, 2.5, 3.0)
HOLD_HOURS = (12, 24, 36, 48)
BASELINE = (24, 1.5, 2.0, 24)
BASE_COST = "round_trip_0_10pct"


def add_vwap_features(bars: Sequence[Bar], features: Sequence[dict], hours: Sequence[int] = VWAP_HOURS) -> list[dict]:
    """Add trailing VWAP distances using only bars available through signal bar i."""
    rows = [dict(row) for row in features]
    for i, bar in enumerate(bars):
        for window in hours:
            key = f"vwap_distance_{window}"
            if i + 1 < window:
                rows[i][key] = None
                continue
            sample = bars[i - window + 1:i + 1]
            volume = sum(item.volume for item in sample)
            vwap = sum(item.close * item.volume for item in sample) / volume if volume else 0.0
            rows[i][key] = bar.close / vwap - 1 if vwap else 0.0
    return rows


def parameter_grid() -> list[tuple[int, float, float, int]]:
    return list(product(VWAP_HOURS, STOP_ATR, TAKE_ATR, HOLD_HOURS))


def is_immediate_neighbor(point: tuple[int, float, float, int], baseline: tuple[int, float, float, int] = BASELINE) -> bool:
    axes = (VWAP_HOURS, STOP_ATR, TAKE_ATR, HOLD_HOURS)
    differences = []
    for axis, value, center in zip(axes, point, baseline):
        if value == center:
            differences.append(0)
            continue
        differences.append(abs(axis.index(value) - axis.index(center)))
    return sum(value != 0 for value in differences) == 1 and max(differences) == 1


def summarize_cluster(rows: Sequence[dict], cost_scenario: str = BASE_COST) -> dict:
    selected = [row for row in rows if row["cost_scenario"] == cost_scenario]
    neighborhood = [row for row in selected if row["is_baseline"] or row["is_immediate_neighbor"]]

    def summary(values: Sequence[dict]) -> dict:
        expectancies = [float(row["expectancy_r"]) for row in values if row["expectancy_r"] is not None]
        totals = [float(row["total_r"]) for row in values]
        return {
            "points": len(values),
            "positive_expectancy_share": sum(value > 0 for value in expectancies) / len(expectancies) if expectancies else None,
            "positive_total_r_share": sum(value > 0 for value in totals) / len(totals) if totals else None,
            "median_expectancy_r": median(expectancies) if expectancies else None,
            "median_total_r": median(totals) if totals else None,
        }

    by_axis: dict[str, dict[str, dict]] = {}
    for name in ("vwap_hours", "stop_atr", "take_atr", "hold_hours"):
        by_axis[name] = {}
        for value in sorted({row[name] for row in selected}):
            by_axis[name][str(value)] = summary([row for row in selected if row[name] == value])
    neighborhood_summary = summary(neighborhood)
    return {
        "cost_scenario": cost_scenario,
        "all_grid": summary(selected),
        "baseline_neighborhood": neighborhood_summary,
        "axis_slices": by_axis,
        "positive_cluster": bool(
            neighborhood_summary["positive_expectancy_share"] is not None
            and neighborhood_summary["positive_expectancy_share"] >= 2 / 3
            and neighborhood_summary["median_expectancy_r"] is not None
            and neighborhood_summary["median_expectancy_r"] > 0
        ),
        "decision_rule": "Cluster is positive when at least two thirds of center plus immediate axis-neighbors have positive expectancy and their median expectancy is positive.",
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run() -> dict:
    btc, _, btc_manifest = download_symbol("BTCUSDT", *YEARS, DATA)
    eth, funding, eth_manifest = download_symbol("ETHUSDT", *YEARS, DATA)
    splits = chronological_splits(len(eth))
    train = list(splits["train"])
    validation = list(splits["validation"])
    assert_selection_indices(train + validation, splits)
    allowed_stop = splits["validation"].stop
    bars = eth[:allowed_stop]
    features = add_vwap_features(bars, make_features(eth, funding, btc)[:allowed_stop])
    funding_map = dict(funding)
    rows: list[dict] = []

    for vwap, stop, take, hold in parameter_grid():
        candidate = Candidate(f"vwap_distance_{vwap}", 1, 0.75, hold, "bear", "high", stop, take)
        calibration = calibrate_candidate(candidate, features, train)
        for cost_name, costs in COST_SCENARIOS.items():
            trades, _ = evaluate_candidate(candidate, bars, features, validation, costs, funding_map, calibration)
            trade_rows = []
            index_by_ts = {bar.ts: i for i, bar in enumerate(bars)}
            for trade in trades:
                signal_i = index_by_ts[trade.signal_ts]
                initial_risk = stop * float(features[signal_i]["atr_24"]) / trade.entry
                trade_rows.append({"result_r": trade.net_return / initial_risk, "net_return": trade.net_return})
            metrics = aggregate_rows(trade_rows)
            point = (vwap, stop, take, hold)
            rows.append({
                "cost_scenario": cost_name,
                "vwap_hours": vwap,
                "stop_atr": stop,
                "take_atr": take,
                "hold_hours": hold,
                "is_baseline": point == BASELINE,
                "is_immediate_neighbor": is_immediate_neighbor(point),
                "threshold": calibration.threshold,
                "rv_median": calibration.rv_median,
                "trades": metrics["trades"],
                "expectancy_r": metrics["expectancy_r"],
                "total_r": metrics["total_r"],
                "profit_factor_r": metrics["profit_factor_r"],
                "max_drawdown_r": metrics["max_drawdown_r"],
                "best_5_share": metrics["concentration"]["best_5_share"],
            })

    report = {
        "phase": "phase-3-parameter-stability",
        "test_opened": False,
        "purpose": "Diagnose the pre-registered parameter surface; do not select the historical maximum.",
        "grid": {
            "vwap_hours": list(VWAP_HOURS), "stop_atr": list(STOP_ATR),
            "take_atr": list(TAKE_ATR), "hold_hours": list(HOLD_HOURS),
            "points": len(parameter_grid()), "cost_scenarios": list(COST_SCENARIOS),
        },
        "baseline": {"vwap_hours": 24, "stop_atr": 1.5, "take_atr": 2.0, "hold_hours": 24},
        "calibration_source": "TRAIN only; one feature-specific threshold and shared rv median frozen before VALIDATION",
        "evaluation_range": [splits["validation"].start, splits["validation"].stop],
        "sealed_test_range": [splits["test"].start, splits["test"].stop],
        "cluster": summarize_cluster(rows),
        "cost_summaries": {name: summarize_cluster(rows, name) for name in COST_SCENARIOS},
        "data_quality": {"BTCUSDT": btc_manifest["quality"], "ETHUSDT": eth_manifest["quality"]},
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "parameter-map.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(OUTPUT / "parameter-map.csv", rows)
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
