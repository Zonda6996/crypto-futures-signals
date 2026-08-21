from __future__ import annotations

import json
import random
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from statistics import mean, median
from typing import Sequence

from .core import Bar, CostModel, chronological_splits
from .data import download_symbol
from .features import make_features
from .phase1_audit import CANDIDATE, r_metrics
from .search import Calibration, calibrate_candidate, evaluate_candidate

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "reports" / "phase4"
YEARS = (2021, 2025)
BASE_COST = CostModel(taker_fee_bps=5, half_spread_bps=0, slippage_bps=0)
HORIZONS = (1, 4, 8, 12, 24)


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def bootstrap_difference(a: Sequence[float], b: Sequence[float], seed: int = 6996, samples: int = 5000) -> dict:
    if not a or not b:
        return {"difference": None, "ci95": [None, None], "probability_positive": None}
    rng = random.Random(seed)
    differences = []
    for _ in range(samples):
        left = mean(rng.choice(a) for _ in a)
        right = mean(rng.choice(b) for _ in b)
        differences.append(left - right)
    return {
        "difference": mean(a) - mean(b),
        "ci95": [percentile(differences, 0.025), percentile(differences, 0.975)],
        "probability_positive": sum(value > 0 for value in differences) / samples,
    }


def event_indices(features: Sequence[dict], available: range, calibration: Calibration) -> dict[str, list[int]]:
    ready = [i for i in available if features[i].get("ready")]
    bear = [i for i in ready if features[i]["btc_regime"] == "bear"]
    bear_high = [i for i in bear if float(features[i]["rv_24"]) >= calibration.rv_median]
    full = [i for i in bear_high if float(features[i]["vwap_distance_24"]) >= calibration.threshold]
    bear_high_not_extended = [i for i in bear_high if float(features[i]["vwap_distance_24"]) < calibration.threshold]
    extended_other_regime = [
        i for i in ready
        if float(features[i]["rv_24"]) >= calibration.rv_median
        and float(features[i]["vwap_distance_24"]) >= calibration.threshold
        and features[i]["btc_regime"] != "bear"
    ]
    return {
        "all_ready": ready,
        "bear": bear,
        "bear_high": bear_high,
        "full_signal": full,
        "bear_high_not_extended": bear_high_not_extended,
        "extended_other_regime": extended_other_regime,
    }


def non_overlapping(indices: Sequence[int], spacing: int = 24) -> list[int]:
    selected: list[int] = []
    last = -spacing - 1
    for index in indices:
        if index > last + spacing:
            selected.append(index)
            last = index
    return selected


def forward_returns(bars: Sequence[Bar], indices: Sequence[int]) -> dict[str, list[float]]:
    result = {str(horizon): [] for horizon in HORIZONS}
    for index in indices:
        entry_index = index + 1
        if entry_index >= len(bars):
            continue
        entry = bars[entry_index].open
        for horizon in HORIZONS:
            exit_index = entry_index + horizon - 1
            if exit_index < len(bars):
                result[str(horizon)].append(bars[exit_index].close / entry - 1)
    return result


def summarize(values: Sequence[float]) -> dict:
    return {
        "observations": len(values),
        "mean": mean(values) if values else None,
        "median": median(values) if values else None,
        "positive_rate": sum(value > 0 for value in values) / len(values) if values else None,
    }


def proxy_summary(features: Sequence[dict], indices: Sequence[int]) -> dict:
    names = ("vwap_distance_24", "btc_return_24", "rv_24", "abnormal_volume_24", "taker_imbalance_24", "relative_strength_24", "funding")
    return {
        name: summarize([float(features[i][name]) for i in indices if features[i].get(name) is not None])
        for name in names
    }


def run() -> dict:
    btc, _, btc_manifest = download_symbol("BTCUSDT", *YEARS, DATA)
    eth, funding, eth_manifest = download_symbol("ETHUSDT", *YEARS, DATA)
    features = make_features(eth, funding, btc)
    splits = chronological_splits(len(eth))
    available = range(splits["train"].start, splits["validation"].stop)
    if available.stop > splits["test"].start:
        raise RuntimeError("Phase 4 attempted to cross the sealed TEST boundary")

    calibration = calibrate_candidate(CANDIDATE, features, list(splits["train"]))
    cohorts = event_indices(features, available, calibration)
    sampled = {name: non_overlapping(indices) for name, indices in cohorts.items()}
    paths = {name: forward_returns(eth, indices) for name, indices in sampled.items()}

    full_24 = paths["full_signal"]["24"]
    comparisons = {}
    for control in ("bear_high_not_extended", "extended_other_regime", "bear_high", "all_ready"):
        comparisons[control] = bootstrap_difference(full_24, paths[control]["24"], seed=6996 + len(comparisons))

    trades, trade_metrics = evaluate_candidate(
        CANDIDATE, eth, features, list(available), BASE_COST, dict(funding), calibration
    )
    trade_rows, r_summary = r_metrics(trades, eth, features)
    trade_metrics.update(r_summary)
    exits = Counter(trade.exit_reason for trade in trades)
    by_exit = {
        reason: summarize([row["result_r"] for row in trade_rows if row["exit_reason"] == reason])
        for reason in sorted(exits)
    }

    report = {
        "phase": "phase-4-economic-mechanism",
        "test_opened": False,
        "scope": {
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "timeframe": "1h",
            "years": list(YEARS),
            "available_indices": [available.start, available.stop],
            "sealed_test_starts_at": splits["test"].start,
        },
        "candidate": asdict(CANDIDATE),
        "calibration_source": "TRAIN only",
        "calibration": asdict(calibration),
        "method": {
            "event_sampling": "At most one event every 25 bars within each cohort to reduce overlapping forward paths.",
            "path_execution": "Signal at closed bar i; hypothetical entry at i+1 open; exits at future closes.",
            "inference": "Deterministic 5,000-draw independent-event bootstrap; descriptive, not proof after candidate selection.",
            "controls": {
                "bear_high_not_extended": "Same BTC bear and high-volatility state, but ETH below the frozen VWAP-distance threshold.",
                "extended_other_regime": "Same ETH extension and high volatility, but BTC is not in the bear regime.",
                "bear_high": "All high-volatility BTC-bear observations, including signal observations.",
                "all_ready": "All causally ready observations in TRAIN+VALIDATION.",
            },
        },
        "cohorts": {
            name: {
                "raw_observations": len(cohorts[name]),
                "non_overlapping_observations": len(sampled[name]),
                "forward_returns": {horizon: summarize(values) for horizon, values in paths[name].items()},
                "state_proxies": proxy_summary(features, sampled[name]),
            }
            for name in cohorts
        },
        "full_signal_24h_comparisons": comparisons,
        "strategy_with_frozen_exits_and_0_10pct_cost": {
            "metrics": trade_metrics,
            "exit_counts": dict(exits),
            "result_r_by_exit": by_exit,
            "funding_total_return": sum(trade.funding_return for trade in trades),
            "cost_total_return": sum(trade.cost_return for trade in trades),
        },
        "data_quality": {"BTCUSDT": btc_manifest["quality"], "ETHUSDT": eth_manifest["quality"]},
        "interpretation_guardrail": "This phase tests whether conditional price paths fit a plausible continuation mechanism. It does not reselect parameters and cannot validate an edge.",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "mechanism.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "test_opened": result["test_opened"],
        "signal_observations": result["cohorts"]["full_signal"]["non_overlapping_observations"],
        "signal_24h": result["cohorts"]["full_signal"]["forward_returns"]["24"],
        "comparisons": result["full_signal_24h_comparisons"],
    }, indent=2))
