from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Sequence

from .core import Bar, CostModel, Trade, assert_selection_indices, chronological_splits, utc_iso
from .data import download_symbol
from .features import make_features
from .phase1_audit import CANDIDATE, COST_SCENARIOS, YEARS
from .search import Calibration, calibrate_candidate, evaluate_candidate

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "reports" / "phase2"
MONTH_MS = 30 * 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class Window:
    calibration_start: int
    calibration_stop: int
    oos_start: int
    oos_stop: int


def _month_start(ts: int) -> datetime:
    value = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    return datetime(value.year, value.month, 1, tzinfo=timezone.utc)


def _add_months(value: datetime, months: int) -> datetime:
    offset = value.month - 1 + months
    return datetime(value.year + offset // 12, offset % 12 + 1, 1, tzinfo=timezone.utc)


def calendar_windows(
    timestamps: Sequence[int], allowed_stop: int, calibration_months: int, oos_months: int, anchored: bool
) -> list[Window]:
    if not timestamps or allowed_stop <= 0 or calibration_months <= 0 or oos_months <= 0:
        return []
    history_start = _month_start(timestamps[0])
    first_oos = _add_months(history_start, calibration_months)
    windows: list[Window] = []
    oos_start_dt = first_oos
    while True:
        oos_stop_dt = _add_months(oos_start_dt, oos_months)
        oos_start = next((i for i, ts in enumerate(timestamps[:allowed_stop]) if ts >= int(oos_start_dt.timestamp() * 1000)), allowed_stop)
        oos_stop = next((i for i, ts in enumerate(timestamps[:allowed_stop]) if ts >= int(oos_stop_dt.timestamp() * 1000)), allowed_stop)
        if oos_start >= allowed_stop or oos_stop <= oos_start:
            break
        calibration_start_dt = history_start if anchored else _add_months(oos_start_dt, -calibration_months)
        calibration_start = next((i for i, ts in enumerate(timestamps[:oos_start]) if ts >= int(calibration_start_dt.timestamp() * 1000)), oos_start)
        if calibration_start >= oos_start:
            break
        windows.append(Window(calibration_start, oos_start, oos_start, oos_stop))
        oos_start_dt = oos_stop_dt
    return windows


def stitch_trades(trades_by_window: Sequence[Sequence[Trade]]) -> list[Trade]:
    stitched: list[Trade] = []
    last_exit = -1
    seen: set[tuple[int, int, int]] = set()
    for trade in sorted((trade for group in trades_by_window for trade in group), key=lambda item: (item.entry_ts, item.exit_ts)):
        identity = (trade.signal_ts, trade.entry_ts, trade.exit_ts)
        if identity not in seen and trade.entry_ts > last_exit:
            stitched.append(trade)
            seen.add(identity)
            last_exit = trade.exit_ts
    return stitched


def r_rows(trades: Sequence[Trade], bars: Sequence[Bar], features: Sequence[dict], window_id_by_signal: dict[int, int]) -> list[dict]:
    index_by_ts = {bar.ts: i for i, bar in enumerate(bars)}
    rows: list[dict] = []
    for trade in trades:
        signal_i = index_by_ts[trade.signal_ts]
        initial_risk = CANDIDATE.stop_atr * float(features[signal_i]["atr_24"]) / trade.entry
        rows.append({
            "window": window_id_by_signal[trade.signal_ts],
            "side": "long",
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
            "result_r": trade.net_return / initial_risk,
        })
    return rows


def aggregate_rows(rows: Sequence[dict]) -> dict:
    rs = [float(row["result_r"]) for row in rows]
    returns = [float(row["net_return"]) for row in rows]
    wins = [value for value in rs if value > 0]
    losses = [value for value in rs if value < 0]
    equity_r = peak_r = max_drawdown_r = 0.0
    compounded = 1.0
    for result_r, net_return in zip(rs, returns):
        equity_r += result_r
        peak_r = max(peak_r, equity_r)
        max_drawdown_r = min(max_drawdown_r, equity_r - peak_r)
        compounded *= 1 + net_return
    ordered = sorted(rs, reverse=True)
    total_r = sum(rs)
    concentration = {
        f"best_{count}_share": (sum(ordered[:count]) / total_r if total_r else None)
        for count in (1, 3, 5)
    }
    return {
        "trades": len(rows),
        "expectancy_r": total_r / len(rows) if rows else None,
        "total_r": total_r,
        "profit_factor_r": sum(wins) / abs(sum(losses)) if losses else None,
        "max_drawdown_r": max_drawdown_r,
        "compounded_return": compounded - 1,
        "concentration": concentration,
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _flatten(prefix: dict, metrics: dict) -> dict:
    return {**prefix, **{key: value for key, value in metrics.items() if key != "concentration"}}


def evaluate_scheme(
    bars: Sequence[Bar], features: Sequence[dict], funding: Sequence[tuple[int, float]], windows: Sequence[Window], costs: CostModel
) -> tuple[dict, list[dict], list[dict], list[dict]]:
    groups: list[list[Trade]] = []
    window_records: list[dict] = []
    signal_windows: dict[int, int] = {}
    for number, window in enumerate(windows, 1):
        calibration_indices = list(range(window.calibration_start, window.calibration_stop))
        calibration = calibrate_candidate(CANDIDATE, features, calibration_indices)
        # Truncation at oos_stop makes it impossible for the simulator to inspect a later bar.
        trades, _ = evaluate_candidate(
            CANDIDATE,
            bars[:window.oos_stop],
            features[:window.oos_stop],
            list(range(window.oos_start, window.oos_stop)),
            costs,
            dict(funding),
            calibration,
        )
        groups.append(trades)
        for trade in trades:
            signal_windows[trade.signal_ts] = number
        rows = r_rows(trades, bars, features, signal_windows)
        window_records.append({
            "window": number,
            "calibration_start": utc_iso(bars[window.calibration_start].ts),
            "calibration_stop": utc_iso(bars[window.calibration_stop - 1].ts),
            "oos_start": utc_iso(bars[window.oos_start].ts),
            "oos_stop": utc_iso(bars[window.oos_stop - 1].ts),
            "threshold": calibration.threshold,
            "rv_median": calibration.rv_median,
            **aggregate_rows(rows),
        })
    stitched = stitch_trades(groups)
    rows = r_rows(stitched, bars, features, signal_windows)
    by_year: dict[int, list[dict]] = {}
    for row in rows:
        year = datetime.fromisoformat(str(row["entry_time"])).year
        by_year.setdefault(year, []).append(row)
    year_records = [{"year": year, **aggregate_rows(values)} for year, values in sorted(by_year.items())]
    summary = aggregate_rows(rows)
    expectancies = [record["expectancy_r"] for record in window_records if record["expectancy_r"] is not None]
    summary.update({
        "windows": len(window_records),
        "profitable_window_share": (
            sum(1 for record in window_records if record["total_r"] > 0) / len(window_records) if window_records else None
        ),
        "median_window_expectancy_r": median(expectancies) if expectancies else None,
    })
    return summary, rows, window_records, year_records


def run() -> dict:
    btc, _, btc_manifest = download_symbol("BTCUSDT", *YEARS, DATA)
    eth, funding, eth_manifest = download_symbol("ETHUSDT", *YEARS, DATA)
    features = make_features(eth, funding, btc)
    splits = chronological_splits(len(eth))
    allowed_stop = splits["validation"].stop
    allowed_indices = list(range(allowed_stop))
    assert_selection_indices(allowed_indices, splits)
    bars = eth[:allowed_stop]
    features = features[:allowed_stop]
    timestamps = [bar.ts for bar in bars]

    report: dict = {
        "phase": "phase-2-walk-forward",
        "test_opened": False,
        "candidate": asdict(CANDIDATE),
        "allowed_range": [0, allowed_stop],
        "sealed_test_range": [splits["test"].start, splits["test"].stop],
        "data_quality": {"BTCUSDT": btc_manifest["quality"], "ETHUSDT": eth_manifest["quality"]},
        "schemes": {},
    }
    all_trades: list[dict] = []
    all_windows: list[dict] = []
    all_years: list[dict] = []
    for calibration_months, oos_months in ((12, 3), (18, 6)):
        for anchored in (True, False):
            mode = "anchored" if anchored else "rolling"
            scheme = f"{mode}_{calibration_months}m_{oos_months}m"
            windows = calendar_windows(timestamps, allowed_stop, calibration_months, oos_months, anchored)
            for window in windows:
                assert_selection_indices(range(window.calibration_start, window.oos_stop), splits)
            report["schemes"][scheme] = {}
            for cost_name, costs in COST_SCENARIOS.items():
                summary, rows, window_records, year_records = evaluate_scheme(bars, features, funding, windows, costs)
                report["schemes"][scheme][cost_name] = {
                    "cost_model": asdict(costs), "summary": summary, "windows": window_records, "years": year_records
                }
                all_trades.extend({"scheme": scheme, "cost_scenario": cost_name, **row} for row in rows)
                all_windows.extend(_flatten({"scheme": scheme, "cost_scenario": cost_name}, row) for row in window_records)
                all_years.extend(_flatten({"scheme": scheme, "cost_scenario": cost_name}, row) for row in year_records)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "walk-forward.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(OUTPUT / "trades.csv", all_trades)
    _write_csv(OUTPUT / "windows.csv", all_windows)
    _write_csv(OUTPUT / "years.csv", all_years)
    return report


if __name__ == "__main__":
    result = run()
    compact = {
        scheme: {cost: values["summary"] for cost, values in scenarios.items()}
        for scheme, scenarios in result["schemes"].items()
    }
    print(json.dumps(compact, indent=2))
