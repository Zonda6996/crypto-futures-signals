from __future__ import annotations

import csv
import json
from dataclasses import asdict, replace
from pathlib import Path
from statistics import mean

from .core import Bar, CostModel, Trade, utc_iso
from .data import INTERVAL_MS, download_symbol
from .features import make_features
from .phase1_audit import CANDIDATE
from .search import calibrate_candidate, evaluate_candidate

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "reports" / "timeframe-robustness"
YEARS = (2021, 2024)
SEALED_TEST_START_TS = 1_735_689_600_000  # 2025-01-01T00:00:00Z; never included
TIMEFRAMES = {"30m": 2, "15m": 4}
COSTS = {
    "round_trip_0_05pct": CostModel(2.5, 0, 0),
    "round_trip_0_10pct": CostModel(5, 0, 0),
    "round_trip_0_16pct": CostModel(5, 1, 2),
}


def scaled_candidate(bars_per_hour: int):
    if bars_per_hour not in TIMEFRAMES.values():
        raise ValueError("only approved M15/M30 scaling is supported")
    return replace(CANDIDATE, horizon=CANDIDATE.horizon * bars_per_hour)


def seal_before_test(bars: list[Bar]) -> list[Bar]:
    sealed = [bar for bar in bars if bar.ts < SEALED_TEST_START_TS]
    if any(bar.ts >= SEALED_TEST_START_TS for bar in sealed):
        raise RuntimeError("sealed TEST bar entered the research sample")
    return sealed


def summarize(trades: list[Trade], bars: list[Bar], features: list[dict], stop_atr: float) -> tuple[dict, list[dict]]:
    index = {bar.ts: i for i, bar in enumerate(bars)}
    values: list[float] = []
    rows: list[dict] = []
    for trade in trades:
        signal_i = index[trade.signal_ts]
        initial_risk = stop_atr * float(features[signal_i]["atr_24"]) / trade.entry
        result_r = trade.net_return / initial_risk
        values.append(result_r)
        rows.append({
            "signal_time": utc_iso(trade.signal_ts),
            "entry_time": utc_iso(trade.entry_ts),
            "exit_time": utc_iso(trade.exit_ts),
            "exit_reason": trade.exit_reason,
            "net_return": trade.net_return,
            "initial_risk_return": initial_risk,
            "result_r": result_r,
        })
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    ordered = sorted(values, reverse=True)
    wins = [value for value in values if value > 0]
    summary = {
        "trades": len(values),
        "expectancy_r": mean(values) if values else None,
        "total_r": sum(values),
        "win_rate": len(wins) / len(values) if values else None,
        "max_drawdown_r": drawdown,
        "best_5_r": sum(ordered[:5]),
        "total_without_best_5_r": sum(ordered[5:]),
        "expectancy_without_best_5_r": mean(ordered[5:]) if len(ordered) > 5 else None,
    }
    return summary, rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run_timeframe(interval: str, bars_per_hour: int) -> dict:
    btc_raw, _, btc_manifest = download_symbol("BTCUSDT", *YEARS, DATA, interval=interval)
    eth_raw, funding, eth_manifest = download_symbol("ETHUSDT", *YEARS, DATA, interval=interval)
    btc, eth = seal_before_test(btc_raw), seal_before_test(eth_raw)
    funding = [(ts, rate) for ts, rate in funding if ts < SEALED_TEST_START_TS]
    if not eth or eth[-1].ts + INTERVAL_MS[interval] > SEALED_TEST_START_TS:
        raise RuntimeError("unexpected TRAIN+VALIDATION boundary")

    features = make_features(eth, funding, btc, bars_per_hour=bars_per_hour)
    train_stop = int(len(eth) * 0.75)  # same 60:20 ratio, conditional on sealed 80% sample
    train = list(range(0, train_stop))
    validation = list(range(train_stop, len(eth)))
    candidate = scaled_candidate(bars_per_hour)
    calibration = calibrate_candidate(candidate, features, train)
    scenarios = {}
    for name, costs in COSTS.items():
        trades, raw_metrics = evaluate_candidate(
            candidate, eth, features, validation, costs, dict(funding), calibration
        )
        summary, rows = summarize(trades, eth, features, candidate.stop_atr)
        write_csv(OUTPUT / f"trades-{interval}-{name}.csv", rows)
        scenarios[name] = {"cost_model": asdict(costs), "raw_metrics": raw_metrics, **summary}

    return {
        "interval": interval,
        "bars_per_hour": bars_per_hour,
        "hour_preserving_windows": {
            "feature_4h_bars": 4 * bars_per_hour,
            "feature_24h_bars": 24 * bars_per_hour,
            "feature_48h_bars": 48 * bars_per_hour,
            "holding_24h_bars": candidate.horizon,
        },
        "sample": {
            "available_bars": len(eth),
            "train_indices": [0, train_stop],
            "validation_indices": [train_stop, len(eth)],
            "last_included_ts": eth[-1].ts,
            "sealed_test_start_ts": SEALED_TEST_START_TS,
        },
        "candidate": asdict(candidate),
        "calibration": asdict(calibration),
        "scenarios": scenarios,
        "data_quality_train_validation_only": {
            "BTCUSDT": btc_manifest["quality"],
            "ETHUSDT": eth_manifest["quality"],
        },
    }


def run() -> dict:
    results = {interval: run_timeframe(interval, factor) for interval, factor in TIMEFRAMES.items()}
    report = {
        "study": "ETHUSDT frozen-candidate out-of-timeframe robustness",
        "test_opened": False,
        "sealed_test_policy": "Bars at or after 2025-01-01T00:00:00Z are removed before features, calibration, or simulation.",
        "selection_policy": "No parameter search; the 1h candidate is frozen and all hour-based windows are mechanically scaled.",
        "interpretation_rule": "Support requires M15 and M30 positive at 0.10%, non-negative at 0.16%, and positive after removing top five trades.",
        "results": results,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "results.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({tf: data["scenarios"] for tf, data in result["results"].items()}, indent=2))
