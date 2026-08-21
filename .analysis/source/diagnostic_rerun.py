from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from research.core import CostModel, chronological_splits
from research.data import download_symbol
from research.features import make_features
from research.search import candidate_grid, evaluate_candidate

ROOT = Path(__file__).resolve().parent
YEARS = (2021, 2025)
SYMBOLS = ("BTCUSDT", "ETHUSDT")
SCENARIOS = {
    "round_trip_0.10pct": CostModel(5.0, 0.0, 0.0),
    "round_trip_0.12pct": CostModel(5.0, 0.0, 1.0),
    "round_trip_0.16pct": CostModel(5.0, 1.0, 2.0),
}


def r_summary(candidate, trades, feature_by_ts):
    values = []
    for trade in trades:
        atr = float(feature_by_ts[trade.signal_ts]["atr_24"])
        initial_risk = candidate.stop_atr * atr / trade.entry
        if initial_risk > 0:
            values.append(trade.net_return / initial_risk)
    if not values:
        return {"expectancy_r": None, "total_r": 0.0, "max_drawdown_r": None}
    cumulative = peak = 0.0
    max_drawdown = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    return {
        "expectancy_r": sum(values) / len(values),
        "total_r": sum(values),
        "max_drawdown_r": max_drawdown,
    }


def main():
    bars_by_symbol, funding_by_symbol, manifests = {}, {}, {}
    for symbol in SYMBOLS:
        bars, funding, manifest = download_symbol(symbol, YEARS[0], YEARS[1], ROOT / "data")
        bars_by_symbol[symbol], funding_by_symbol[symbol], manifests[symbol] = bars, funding, manifest

    btc = bars_by_symbol["BTCUSDT"]
    prepared = {}
    for symbol in SYMBOLS:
        bars, funding = bars_by_symbol[symbol], funding_by_symbol[symbol]
        features = make_features(bars, funding, btc if symbol != "BTCUSDT" else bars)
        prepared[symbol] = (bars, funding, features, {row["ts"]: row for row in features if row.get("ready")})

    output = {"scope": {"years": YEARS, "symbols": SYMBOLS}, "cost_scenarios": {}, "data_quality": manifests}
    for scenario_name, costs in SCENARIOS.items():
        records = []
        for symbol in SYMBOLS:
            bars, funding, features, feature_by_ts = prepared[symbol]
            splits = chronological_splits(len(bars))
            funding_map = dict(funding)
            for candidate in candidate_grid():
                _, train = evaluate_candidate(candidate, bars, features, list(splits["train"]), costs, funding_map)
                trades, validation = evaluate_candidate(candidate, bars, features, list(splits["validation"]), costs, funding_map)
                validation.update(r_summary(candidate, trades, feature_by_ts))
                records.append({"symbol": symbol, "candidate": asdict(candidate), "train": train, "validation": validation})
        ranked = sorted(records, key=lambda row: (row["validation"]["expectancy_r"] if row["validation"]["expectancy_r"] is not None else -999, row["validation"]["trades"]), reverse=True)
        output["cost_scenarios"][scenario_name] = {
            "round_trip_return": costs.round_trip_return,
            "candidates_tested": len(records),
            "positive_expectancy_with_30_trades": sum(1 for row in records if row["validation"]["trades"] >= 30 and (row["validation"]["expectancy_r"] or 0) > 0),
            "top20": ranked[:20],
        }
        print(f"finished {scenario_name}: best={ranked[0]['validation']['expectancy_r']:.4f}R", flush=True)

    target = ROOT / "reports" / "diagnostic-bingx-costs.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
