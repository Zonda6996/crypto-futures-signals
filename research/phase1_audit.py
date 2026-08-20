from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from .core import Bar, CostModel, chronological_splits, utc_iso
from .data import download_symbol
from .features import make_features
from .search import Candidate, calibrate_candidate, evaluate_candidate

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "reports" / "phase1"
YEARS = (2021, 2025)
CANDIDATE = Candidate("vwap_distance_24", 1, 0.75, 24, "bear", "high", 1.5, 2.0)
COST_SCENARIOS = {
    "round_trip_0_05pct": CostModel(taker_fee_bps=2.5, half_spread_bps=0, slippage_bps=0),
    "round_trip_0_10pct": CostModel(taker_fee_bps=5, half_spread_bps=0, slippage_bps=0),
    "round_trip_0_12pct": CostModel(taker_fee_bps=5, half_spread_bps=0, slippage_bps=1),
    "round_trip_0_16pct": CostModel(taker_fee_bps=5, half_spread_bps=1, slippage_bps=2),
}


def r_metrics(trades, bars: list[Bar], features: list[dict]) -> tuple[list[dict], dict]:
    index_by_ts = {bar.ts: index for index, bar in enumerate(bars)}
    rows, rs = [], []
    for trade in trades:
        signal_i = index_by_ts[trade.signal_ts]
        entry_i = index_by_ts[trade.entry_ts]
        exit_i = index_by_ts[trade.exit_ts]
        initial_risk = CANDIDATE.stop_atr * float(features[signal_i]["atr_24"]) / trade.entry
        result_r = trade.net_return / initial_risk
        path = bars[entry_i:exit_i + 1]
        favorable = max(trade.side * (price / trade.entry - 1) for bar in path for price in (bar.low, bar.high))
        adverse = min(trade.side * (price / trade.entry - 1) for bar in path for price in (bar.low, bar.high))
        rs.append(result_r)
        rows.append({
            "side": "long" if trade.side == 1 else "short",
            "signal_time": utc_iso(trade.signal_ts),
            "entry_time": utc_iso(trade.entry_ts),
            "exit_time": utc_iso(trade.exit_ts),
            "entry": trade.entry,
            "exit": trade.exit,
            "exit_reason": trade.exit_reason,
            "gross_return": trade.gross_return,
            "funding_return": trade.funding_return,
            "cost_return": trade.cost_return,
            "net_return": trade.net_return,
            "initial_risk_return": initial_risk,
            "result_r": result_r,
            "mae_r": adverse / initial_risk,
            "mfe_r": favorable / initial_risk,
        })
    equity = peak = 0.0
    max_drawdown = 0.0
    for value in rs:
        equity += value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    summary = {
        "expectancy_r": sum(rs) / len(rs) if rs else None,
        "total_r": sum(rs),
        "max_drawdown_r": max_drawdown,
    }
    return rows, summary


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run() -> dict:
    btc, _, btc_manifest = download_symbol("BTCUSDT", *YEARS, DATA)
    eth, funding, eth_manifest = download_symbol("ETHUSDT", *YEARS, DATA)
    features = make_features(eth, funding, btc)
    splits = chronological_splits(len(eth))
    train = list(splits["train"])
    validation = list(splits["validation"])
    calibration = calibrate_candidate(CANDIDATE, features, train)
    scenarios = {}
    for name, costs in COST_SCENARIOS.items():
        train_trades, train_metrics = evaluate_candidate(CANDIDATE, eth, features, train, costs, dict(funding), calibration)
        validation_trades, validation_metrics = evaluate_candidate(
            CANDIDATE, eth, features, validation, costs, dict(funding), calibration
        )
        train_rows, train_r = r_metrics(train_trades, eth, features)
        validation_rows, validation_r = r_metrics(validation_trades, eth, features)
        train_metrics.update(train_r)
        validation_metrics.update(validation_r)
        write_csv(OUTPUT / f"trades-{name}-train.csv", train_rows)
        write_csv(OUTPUT / f"trades-{name}-validation.csv", validation_rows)
        scenarios[name] = {"cost_model": asdict(costs), "train": train_metrics, "validation": validation_metrics}
    report = {
        "phase": "phase-1-baseline-audit",
        "test_opened": False,
        "candidate": asdict(CANDIDATE),
        "calibration_source": "TRAIN only",
        "calibration": asdict(calibration),
        "split_boundaries": {key: [value.start, value.stop] for key, value in splits.items()},
        "scenarios": scenarios,
        "data_quality": {"BTCUSDT": btc_manifest["quality"], "ETHUSDT": eth_manifest["quality"]},
        "audit_findings": [
            "Signals use closed bar i and execute at bar i+1 open.",
            "Same-bar stop/take collision resolves to stop.",
            "Only one position is allowed at a time per symbol.",
            "Funding is backward-asof joined and charged only at exact funding timestamps while held.",
            "Original diagnostic recalibrated feature and volatility quantiles on VALIDATION; this leaked validation distribution information. Phase 1 freezes both values on TRAIN.",
            "CostModel.taker_fee_bps is per execution side, so 5 bps produces 10 bps round trip before spread/slippage.",
            "TEST remains sealed and is not evaluated in this phase.",
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "audit.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({name: value["validation"] for name, value in result["scenarios"].items()}, indent=2))
