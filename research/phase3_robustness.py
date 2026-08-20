from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from statistics import median

from .core import CostModel, chronological_splits
from .data import download_symbol
from .features import make_features
from .phase1_audit import CANDIDATE, r_metrics
from .phase2_walk_forward import concentration, summarize_r, walk_forward_folds
from .search import Candidate, calibrate_candidate, evaluate_candidate

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "reports" / "phase3"
YEARS = (2021, 2025)
TEST_START = 35_059

COSTS = {
    "round_trip_0.05pct": CostModel(taker_fee_bps=2.5, half_spread_bps=0, slippage_bps=0),
    "round_trip_0.10pct": CostModel(taker_fee_bps=5, half_spread_bps=0, slippage_bps=0),
    "round_trip_0.12pct": CostModel(taker_fee_bps=5, half_spread_bps=0, slippage_bps=1),
    "round_trip_0.16pct": CostModel(taker_fee_bps=5, half_spread_bps=1, slippage_bps=2),
}
WINDOWS = {
    "short": (12_000, 4_500),
    "phase2_base": (14_000, 5_250),
    "long": (16_000, 6_000),
}


def neighbor_candidates() -> dict[str, Candidate]:
    variants = {"frozen": CANDIDATE}
    for q in (0.70, 0.80):
        variants[f"threshold_q_{q:.2f}"] = replace(CANDIDATE, threshold_q=q)
    for stop in (1.2, 1.8, 2.0):
        variants[f"stop_atr_{stop:.1f}"] = replace(CANDIDATE, stop_atr=stop)
    for take in (1.5, 2.5, 3.0):
        variants[f"take_atr_{take:.1f}"] = replace(CANDIDATE, take_atr=take)
    for horizon in (12, 36, 48):
        variants[f"horizon_{horizon}"] = replace(CANDIDATE, horizon=horizon)
    return variants


def evaluate_walk_forward(candidate, bars, features, funding_map, available, mode, initial, oos, costs):
    values = []
    fold_totals = []
    rows = []
    for number, fold in enumerate(walk_forward_folds(available, initial, oos, mode), 1):
        calibration = calibrate_candidate(candidate, features, list(fold["calibration"]))
        trades, _ = evaluate_candidate(candidate, bars, features, list(fold["oos"]), costs, funding_map, calibration)
        trade_rows, _ = r_metrics(trades, bars, features)
        fold_values = [float(row["result_r"]) for row in trade_rows]
        values.extend(fold_values)
        fold_totals.append(sum(fold_values))
        rows.extend({**row, "fold": number} for row in trade_rows)
    summary = summarize_r(values)
    summary.update({
        "positive_folds": sum(value > 0 for value in fold_totals),
        "total_folds": len(fold_totals),
        "fold_total_r": fold_totals,
        "concentration": concentration(values),
    })
    return summary, rows


def run():
    btc, _, btc_manifest = download_symbol("BTCUSDT", *YEARS, DATA)
    eth, funding, eth_manifest = download_symbol("ETHUSDT", *YEARS, DATA)
    features = make_features(eth, funding, btc)
    splits = chronological_splits(len(eth))
    available = range(splits["train"].start, splits["validation"].stop)
    if available.stop != splits["test"].start or available.stop != TEST_START:
        raise RuntimeError("Phase 3 boundary must stop exactly before sealed TEST")
    funding_map = dict(funding)

    cost_sensitivity = {}
    for label, costs in COSTS.items():
        cost_sensitivity[label] = {}
        for mode in ("anchored", "rolling"):
            result, _ = evaluate_walk_forward(CANDIDATE, eth, features, funding_map, available, mode, 14_000, 5_250, costs)
            cost_sensitivity[label][mode] = result

    window_sensitivity = {}
    for label, (initial, oos) in WINDOWS.items():
        window_sensitivity[label] = {}
        for mode in ("anchored", "rolling"):
            result, _ = evaluate_walk_forward(CANDIDATE, eth, features, funding_map, available, mode, initial, oos, COSTS["round_trip_0.10pct"])
            window_sensitivity[label][mode] = result

    parameter_map = {}
    for label, candidate in neighbor_candidates().items():
        parameter_map[label] = {"candidate": asdict(candidate), "modes": {}}
        for mode in ("anchored", "rolling"):
            result, _ = evaluate_walk_forward(candidate, eth, features, funding_map, available, mode, 14_000, 5_250, COSTS["round_trip_0.10pct"])
            parameter_map[label]["modes"][mode] = result

    neighbors = [value for key, value in parameter_map.items() if key != "frozen"]
    positive_neighbor_share = {
        mode: sum(item["modes"][mode]["total_r"] > 0 for item in neighbors) / len(neighbors)
        for mode in ("anchored", "rolling")
    }
    median_neighbor_total_r = {
        mode: median(item["modes"][mode]["total_r"] for item in neighbors)
        for mode in ("anchored", "rolling")
    }
    stress = cost_sensitivity["round_trip_0.16pct"]
    base = parameter_map["frozen"]["modes"]
    passed = all(stress[mode]["total_r"] > 0 for mode in ("anchored", "rolling")) and all(
        positive_neighbor_share[mode] >= 0.70 and median_neighbor_total_r[mode] > 0
        for mode in ("anchored", "rolling")
    ) and all(base[mode]["concentration"]["total_without_best_5_r"] > 0 for mode in ("anchored", "rolling"))

    report = {
        "phase": "phase-3-robustness",
        "test_opened": False,
        "scope": {"available_indices": [available.start, available.stop], "sealed_test_starts_at": splits["test"].start},
        "frozen_candidate": asdict(CANDIDATE),
        "method": {
            "principle": "Predeclared one-factor-at-a-time diagnostics; no variant replaces the frozen candidate.",
            "costs": list(COSTS),
            "windows": {key: {"initial_bars": value[0], "oos_bars": value[1]} for key, value in WINDOWS.items()},
            "parameter_policy": "Threshold, stop, take and horizon are perturbed one at a time around the frozen point.",
        },
        "cost_sensitivity": cost_sensitivity,
        "window_sensitivity": window_sensitivity,
        "parameter_map": parameter_map,
        "diagnostics": {"positive_neighbor_share": positive_neighbor_share, "median_neighbor_total_r": median_neighbor_total_r},
        "decision_rule": {
            "requirements": "Both modes positive at 0.16% cost, >=70% positive neighbors with positive median, and both frozen modes positive after removing best five trades.",
            "passed": passed,
            "consequence": "TEST remains sealed regardless; opening requires a separate explicit decision after reviewing Phase 3.",
        },
        "data_quality": {"BTCUSDT": btc_manifest["quality"], "ETHUSDT": eth_manifest["quality"]},
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "robustness.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({"diagnostics": result["diagnostics"], "decision_rule": result["decision_rule"]}, indent=2))
