from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from typing import Sequence

from .core import Bar, CostModel, Trade, chronological_splits, utc_iso
from .data import download_symbol
from .features import make_features
from .phase1_audit import CANDIDATE, r_metrics
from .search import calibrate_candidate, evaluate_candidate

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "reports" / "phase2-repeat"
YEARS = (2021, 2025)
BASE_COST = CostModel(taker_fee_bps=5, half_spread_bps=0, slippage_bps=0)
INITIAL_TRAIN_BARS = 14_000
OOS_BARS = 5_250


def walk_forward_folds(available: range, initial_train_bars: int, oos_bars: int, mode: str) -> list[dict[str, range]]:
    if mode not in {"anchored", "rolling"}:
        raise ValueError("mode must be anchored or rolling")
    if initial_train_bars <= 0 or oos_bars <= 0:
        raise ValueError("window sizes must be positive")
    folds = []
    oos_start = available.start + initial_train_bars
    while oos_start + oos_bars <= available.stop:
        oos_stop = oos_start + oos_bars
        calibration_start = available.start if mode == "anchored" else max(available.start, oos_start - initial_train_bars)
        folds.append({
            "calibration": range(calibration_start, oos_start),
            "oos": range(oos_start, oos_stop),
        })
        oos_start = oos_stop
    return folds


def summarize_r(values: Sequence[float]) -> dict:
    equity = peak = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    return {
        "trades": len(values),
        "expectancy_r": mean(values) if values else None,
        "total_r": sum(values),
        "profit_factor_r": sum(wins) / abs(sum(losses)) if losses else None,
        "win_rate": len(wins) / len(values) if values else None,
        "max_drawdown_r": max_drawdown,
    }


def concentration(values: Sequence[float]) -> dict:
    total = sum(values)
    ordered = sorted(values, reverse=True)
    return {
        "best_5_r": sum(ordered[:5]),
        "best_10_r": sum(ordered[:10]),
        "share_from_best_5": sum(ordered[:5]) / total if total else None,
        "total_without_best_5_r": sum(ordered[5:]),
        "total_without_best_10_r": sum(ordered[10:]),
    }


def run_mode(mode: str, bars: list[Bar], features: list[dict], funding: list[tuple[int, float]], available: range) -> dict:
    folds = walk_forward_folds(available, INITIAL_TRAIN_BARS, OOS_BARS, mode)
    funding_map = dict(funding)
    all_rows: list[dict] = []
    fold_results = []
    all_trades: list[Trade] = []

    for number, fold in enumerate(folds, 1):
        calibration = calibrate_candidate(CANDIDATE, features, list(fold["calibration"]))
        trades, metrics = evaluate_candidate(
            CANDIDATE, bars, features, list(fold["oos"]), BASE_COST, funding_map, calibration
        )
        rows, r_summary = r_metrics(trades, bars, features)
        for row in rows:
            row["fold"] = number
            row["mode"] = mode
        all_rows.extend(rows)
        all_trades.extend(trades)
        metrics.update(r_summary)
        fold_results.append({
            "fold": number,
            "calibration_indices": [fold["calibration"].start, fold["calibration"].stop],
            "oos_indices": [fold["oos"].start, fold["oos"].stop],
            "calibration": asdict(calibration),
            "metrics": metrics,
        })

    all_rows.sort(key=lambda row: row["entry_time"])
    r_values = [float(row["result_r"]) for row in all_rows]
    by_year: dict[str, list[float]] = defaultdict(list)
    for row in all_rows:
        by_year[row["entry_time"][:4]].append(float(row["result_r"]))

    return {
        "mode": mode,
        "folds": fold_results,
        "combined_oos": summarize_r(r_values),
        "by_year": {year: summarize_r(values) for year, values in sorted(by_year.items())},
        "concentration": concentration(r_values),
        "positive_folds": sum((fold["metrics"]["total_r"] or 0) > 0 for fold in fold_results),
        "total_folds": len(fold_results),
        "trade_rows": all_rows,
        "trade_timestamps_unique": len({trade.entry_ts for trade in all_trades}) == len(all_trades),
    }


def run() -> dict:
    btc, _, btc_manifest = download_symbol("BTCUSDT", *YEARS, DATA)
    eth, funding, eth_manifest = download_symbol("ETHUSDT", *YEARS, DATA)
    features = make_features(eth, funding, btc)
    splits = chronological_splits(len(eth))
    available = range(splits["train"].start, splits["validation"].stop)
    if available.stop != splits["test"].start:
        raise RuntimeError("Walk-forward boundary must end exactly where sealed TEST begins")

    modes = {mode: run_mode(mode, eth, features, funding, available) for mode in ("anchored", "rolling")}
    report = {
        "phase": "phase-2-walk-forward-repeat-supplement",
        "test_opened": False,
        "scope": {
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "timeframe": "1h",
            "years": list(YEARS),
            "available_indices": [available.start, available.stop],
            "sealed_test_starts_at": splits["test"].start,
        },
        "candidate": asdict(CANDIDATE),
        "cost_model": asdict(BASE_COST),
        "window_policy": {
            "initial_train_bars": INITIAL_TRAIN_BARS,
            "oos_bars": OOS_BARS,
            "excluded_tail_bars": available.stop - modes["anchored"]["folds"][-1]["oos_indices"][1],
            "tail_policy": "Only complete, comparable OOS windows are evaluated; the short remainder stays inside TRAIN+VALIDATION and is not scored.",
            "anchored": "Calibration begins at index 0 and expands using past data only.",
            "rolling": "Calibration uses the trailing 14,000 bars before each OOS window.",
            "parameters": "Candidate parameters remain frozen; only feature threshold and volatility median are recalibrated on past data.",
        },
        "modes": modes,
        "data_quality": {"BTCUSDT": btc_manifest["quality"], "ETHUSDT": eth_manifest["quality"]},
        "decision_rule": "Do not open TEST unless combined OOS is positive and profits are distributed across folds; this report records evidence without changing the rule after seeing results.",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "walk-forward.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    for mode, result in modes.items():
        rows = result.pop("trade_rows")
        report["modes"][mode]["trade_rows_file"] = f"trades-{mode}.json"
        (OUTPUT / f"trades-{mode}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (OUTPUT / "walk-forward.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        mode: {
            "combined_oos": value["combined_oos"],
            "positive_folds": value["positive_folds"],
            "total_folds": value["total_folds"],
        }
        for mode, value in result["modes"].items()
    }, indent=2))
