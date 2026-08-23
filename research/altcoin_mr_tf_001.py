"""ALTCOIN_MR_TF_001 deterministic sweep runner (mean reversion x timeframe).

Implements the frozen protocol `docs/ALTCOIN_MR_TF_001_FROZEN_PROTOCOL.md`: a sharp
single-bar move (return beyond z trailing-volatility sigmas) is faded on the NEXT
close with two exit geometries — a fixed 3-day-equivalent hold or a 1:1 ATR
stop/take pair — across four signal timeframes (1d, 2h, 4h, 1h), long-only or both
sides. One open trade per symbol; trades pool into the program-standard daily
closed-equity curve and pass the unchanged gate stack (SPA, Holm, DSR, heritage
report, block bootstrap, neighbours, stress, eleven calendar half-year folds).

The monitor reserve (2026-07..) is never read by this module.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

from research.altcoin_carry_001 import DAY_MS, max_drawdown_from_returns
from research.altcoin_carry_sl_001 import wilder_atr
from research.altcoin_multitf_gates import (
    compute_metrics,
    is_eligible,
    ordering_key,
    neighbor_profitability as _generic_neighbor_profitability,
)
from research.altcoin_multitf_inputs import UNIVERSE_SYMBOLS
from research.altcoin_multitf_phase3 import write_json_atomic
from research.altcoin_multitf_phase4 import Diagnostics, Evaluation, Trade
from research.altcoin_multitf_phase7 import (
    DECIDE_END_EXCLUSIVE_MS,
    DECIDE_START_MS,
    FOLD_BOUNDS_007,
    sha256_file,
)
from research.altcoin_multitf_statistics import (
    circular_block_bootstrap_mean_ci,
    deflated_sharpe_probability,
    holm_adjusted,
    newey_west_lrv,
    normal_cdf,
    nw_lag,
    sharpe_ratio,
    spa_pvalues,
)

PROTOCOL_ID = "ALTCOIN_MR_TF-001"
PROTOCOL_DOC = Path("docs/ALTCOIN_MR_TF_001_FROZEN_PROTOCOL.md")
ARTIFACTS = Path("reports/artifacts/altcoin-mr-tf-001")
SUPPLEMENT_ROOT = "altcoin-multitf-006-supplement"

SEED_SWEEP = 20261012
SEED_BOOTSTRAP = 20261013
SEED_SPA = 20261014

TF_MINUTES = {"1d": 1440, "2h": 120, "4h": 240, "1h": 60}
HOLD_BARS = {"1d": 3, "2h": 36, "4h": 18, "1h": 72}  # 3 days in each TF's bars
Z_VALUES = (2.0, 3.0)
SIDES = ("long", "both")
EXITS = ("time3", "tp11")
EXPECTED_GRID_COUNT = 32

ATR_PERIOD = 14
SIGMA_WINDOW = 30
STOP_ATR_MULT = 2.0  # tp11: stop 2xATR, take 1:1 -> 2xATR
COST_PER_FILL_BPS = 6.0  # fee 4 + slippage 2
ROUND_TRIP_COST = 2.0 * COST_PER_FILL_BPS / 1e4
MAKER_ROUND_TRIP = 2.0 * 3.0 / 1e4
STRESS_COSTS = {"fee_double": 2.0 * 10.0 / 1e4, "slippage_triple": 2.0 * 10.0 / 1e4}

NOTIONAL_PER_TRADE = 10_000.0
HERITAGE_TRIALS = 6_090 + EXPECTED_GRID_COUNT  # 6,122
TEMPORAL_MIN_POSITIVE_FOLDS = 7
NEIGHBOR_MIN_PROFITABLE_SHARE = 0.60

SPA_REPLICATES = 1000
BOOTSTRAP_REPLICATES = 2000

SWEEP_SCHEMA = "altcoin-mr-tf-001-sweep-v1"

PRIOR_INPUT_HASHES = {
    "primary_archive_sha256": "665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d",
    "supplement_archive_sha256": "a753585a11beb7bad74f9262920324fe8315a681b6dd108db072790bad47bd5b",
    "supplement_v2_archive_sha256": "487046fad5659e427075ca2b2b676bb3213da85276848129ba5eb21f00d10c56",
}


class MrError(RuntimeError):
    pass


def item_key(tf: str, z: float, side: str, exit_mode: str) -> str:
    payload = json.dumps({"tf": tf, "z": z, "side": side, "exit": exit_mode},
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def frozen_grid() -> tuple[dict, ...]:
    items = []
    seen = set()
    for tf in TF_MINUTES:
        for z in Z_VALUES:
            for side in SIDES:
                for exit_mode in EXITS:
                    key = item_key(tf, z, side, exit_mode)
                    if key in seen:
                        raise MrError(f"key collision: {key}")
                    seen.add(key)
                    items.append({"key": key, "tf": tf, "z": z, "side": side, "exit": exit_mode})
    items.sort(key=lambda i: i["key"])
    if len(items) != EXPECTED_GRID_COUNT:
        raise MrError(f"grid mismatch: {len(items)} != {EXPECTED_GRID_COUNT}")
    return tuple(items)


ITEMS_BY_KEY = {i["key"]: i for i in frozen_grid()}


# ---------------------------------------------------------------------------
# data


class TfSeries:
    def __init__(self, opens: list[int], closes: list[float], highs: list[float], lows: list[float]) -> None:
        self.opens = opens
        self.closes = closes
        self.highs = highs
        self.lows = lows
        self.atr = self._wilder()

    def _wilder(self) -> list[float | None]:
        n = ATR_PERIOD
        out: list[float | None] = [None] * len(self.closes)
        smoothed = None
        trs: list[float] = []
        for i in range(1, len(self.closes)):
            tr = max(self.highs[i] - self.lows[i],
                     abs(self.highs[i] - self.closes[i - 1]),
                     abs(self.lows[i] - self.closes[i - 1]))
            if smoothed is None:
                trs.append(tr)
                if len(trs) == n:
                    smoothed = sum(trs) / n
                    out[i] = smoothed
                continue
            smoothed = ((n - 1) * smoothed + tr) / n
            out[i] = smoothed
        return out


class MrData:
    """Per-timeframe OHLC series for the universe plus funding events per symbol."""

    def __init__(self, series: dict[str, dict[str, TfSeries]], funding: dict[str, tuple[list[int], list[float]]]) -> None:
        self.series = series
        self.funding = funding

    @classmethod
    def load(cls, merged_root: Path) -> "MrData":
        base = merged_root.resolve() / SUPPLEMENT_ROOT / "development" / "normalized"
        series: dict[str, dict[str, TfSeries]] = {}
        funding: dict[str, tuple[list[int], list[float]]] = {}
        for symbol in UNIVERSE_SYMBOLS:
            fpath = base / "funding" / symbol / f"{symbol}-funding.csv.gz"
            ts_list: list[int] = []
            rates: list[float] = []
            with gzip.open(fpath, "rt", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    ts = int(row["funding_time_ms"])
                    if ts >= DECIDE_END_EXCLUSIVE_MS:
                        continue
                    ts_list.append(ts)
                    rates.append(float(row["funding_rate"]))
            funding[symbol] = (ts_list, rates)
            series[symbol] = {}
            for tf_name in TF_MINUTES:
                path = base / "klines" / symbol / f"{symbol}-{tf_name}.csv.gz"
                if not path.is_file():
                    raise MrError(f"missing normalized series: {path}")
                opens, closes, highs, lows = [], [], [], []
                with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
                    for row in csv.DictReader(handle):
                        open_ms = int(row["open_time_ms"])
                        if open_ms >= DECIDE_END_EXCLUSIVE_MS:
                            continue
                        opens.append(open_ms)
                        closes.append(float(row["close"]))
                        highs.append(float(row["high"]))
                        lows.append(float(row["low"]))
                if not opens:
                    raise MrError(f"empty series: {path}")
                series[symbol][tf_name] = TfSeries(opens, closes, highs, lows)
        return cls(series, funding)


def _funding_between(data: MrData, symbol: str, start_exclusive: int, end_inclusive: int) -> float:
    ts_list, rates = data.funding[symbol]
    lo = bisect.bisect_right(ts_list, start_exclusive)
    hi = bisect.bisect_right(ts_list, end_inclusive)
    return sum(rates[lo:hi])


def generate_trades(item: dict, data: MrData, round_trip_cost: float, *, funding_mode: str | None = None):
    """Returns {symbol: [Trade, ...]} for one configuration."""
    tf = item["tf"]
    z = item["z"]
    side_mode = item["side"]
    exit_mode = item["exit"]
    hold = HOLD_BARS[tf]
    out: dict[str, list[Trade]] = {}

    for symbol in UNIVERSE_SYMBOLS:
        series = data.series[symbol][tf]
        opens, closes = series.opens, series.closes
        trades: list[Trade] = []
        i = bisect.bisect_left(opens, DECIDE_START_MS)
        while i < len(opens):
            if i < SIGMA_WINDOW or i == 0:
                i += 1
                continue
            ret = closes[i] / closes[i - 1] - 1.0
            rets = [closes[k] / closes[k - 1] - 1.0 for k in range(i - SIGMA_WINDOW, i)]
            mean = sum(rets) / SIGMA_WINDOW
            sigma = (sum((v - mean) ** 2 for v in rets) / SIGMA_WINDOW) ** 0.5
            if sigma <= 0:
                i += 1
                continue
            side = 0
            if ret <= -z * sigma:
                side = 1
            elif side_mode == "both" and ret >= z * sigma:
                side = -1
            if side == 0:
                i += 1
                continue
            entry_price = closes[i]
            entry_ts = opens[i]
            atr = series.atr[i]
            exit_index = None
            exit_reason = None
            if exit_mode == "time3":
                j = i + hold
                if j >= len(opens) or opens[j] >= DECIDE_END_EXCLUSIVE_MS:
                    break  # no exit bar inside the window: symbol done
                exit_index, exit_reason = j, "time"
            else:
                dist = STOP_ATR_MULT * atr if atr else None
                if dist is None or dist <= 0:
                    i += 1
                    continue
                j = i + 1
                exit_index, exit_reason = None, None
                while j < len(opens) and opens[j] < DECIDE_END_EXCLUSIVE_MS:
                    px = closes[j]
                    if side > 0 and px <= entry_price - dist:
                        exit_index, exit_reason = j, "stop"
                        break
                    if side < 0 and px >= entry_price + dist:
                        exit_index, exit_reason = j, "stop"
                        break
                    if side > 0 and px >= entry_price + dist:
                        exit_index, exit_reason = j, "take"
                        break
                    if side < 0 and px <= entry_price - dist:
                        exit_index, exit_reason = j, "take"
                        break
                    j += 1
                if exit_index is None:
                    break  # ran out of window bars with a position open
            exit_price = closes[exit_index]
            exit_ts = opens[exit_index]
            price_pnl = side * (exit_price - entry_price) / entry_price
            fsum = _funding_between(data, symbol, entry_ts, exit_ts)
            if funding_mode == "half":
                fsum *= 0.5
            elif funding_mode == "flipped":
                fsum = -fsum
            pnl_fraction = price_pnl - round_trip_cost - side * fsum
            trades.append(Trade(
                side=side,
                quantity=NOTIONAL_PER_TRADE,
                entry_time_ms=entry_ts,
                exit_time_ms=exit_ts,
                entry_price=entry_price,
                exit_price=exit_price,
                gross_pnl=price_pnl * NOTIONAL_PER_TRADE,
                fees=COST_PER_FILL_BPS / 1e4 * NOTIONAL_PER_TRADE * 0,
                slippage=0.0,
                funding=-side * fsum * NOTIONAL_PER_TRADE,
                net_pnl=pnl_fraction * NOTIONAL_PER_TRADE,
                return_on_equity=pnl_fraction,
                exit_reason=exit_reason,
            ))
            i = exit_index + 1  # one open trade per symbol: resume after exit
        out[symbol] = trades
    return out


def config_metrics_row(item: dict, trades_by_symbol: dict) -> dict:
    evaluations = {
        symbol: Evaluation(item["key"], True, tuple(trades), 0.0, Diagnostics())
        for symbol, trades in trades_by_symbol.items()
    }
    metrics = compute_metrics(
        item["key"],
        evaluations,
        initial_equity=NOTIONAL_PER_TRADE,
        window_start_ms=DECIDE_START_MS,
        window_end_ms=DECIDE_END_EXCLUSIVE_MS,
        fold_bounds_override=FOLD_BOUNDS_007,
    )
    return metrics


def invalid_row(item: dict, reason: str) -> dict:
    return {
        "key": item["key"], "tf": item["tf"], "z": item["z"], "side": item["side"],
        "exit": item["exit"], "valid": False, "invalid_reason": reason,
        "trades": 0, "net_return": 0.0, "daily_sharpe": None, "annualized_sharpe": None,
        "median_fold_sharpe": 0.0, "fold_sharpes": [], "fold_net_returns": [],
        "positive_folds": 0, "max_drawdown": 0.0, "active_assets": 0, "asset_names": [],
        "max_asset_positive_share": 1.0, "long_trades": 0, "short_trades": 0,
        "long_net_pnl": 0.0, "short_net_pnl": 0.0, "daily_returns": [],
    }


def row_from_metrics(item: dict, metrics) -> dict:
    return {
        "key": item["key"], "tf": item["tf"], "z": item["z"], "side": item["side"],
        "exit": item["exit"], "valid": metrics.valid, "invalid_reason": metrics.invalid_reason,
        "trades": metrics.trades, "net_return": metrics.net_return,
        "daily_sharpe": metrics.daily_sharpe, "annualized_sharpe": metrics.annualized_sharpe,
        "median_fold_sharpe": metrics.median_fold_sharpe, "fold_sharpes": list(metrics.fold_sharpes),
        "fold_net_returns": list(metrics.fold_net_returns), "positive_folds": metrics.positive_folds,
        "max_drawdown": metrics.max_drawdown, "active_assets": metrics.active_assets,
        "asset_names": list(metrics.asset_names),
        "max_asset_positive_share": metrics.max_asset_positive_share,
        "long_trades": metrics.long_trades, "short_trades": metrics.short_trades,
        "long_net_pnl": metrics.long_net_pnl, "short_net_pnl": metrics.short_net_pnl,
        "daily_returns": list(metrics.daily_returns),
    }


def metrics_from_row(row: dict):
    from research.altcoin_multitf_gates import ConfigMetrics

    fields = {k: v for k, v in row.items() if k in ConfigMetrics.__dataclass_fields__}
    fields["config_key"] = row["key"]
    fields["zero_trade"] = row["trades"] == 0
    fields["net_pnl"] = row["net_return"] * NOTIONAL_PER_TRADE
    fields["mean_trade_return"] = 0.0
    fields["ending_equity"] = 0.0
    fields["rejected_orders_total"] = 0
    fields["missing_bars"] = 0
    fields["funding_events"] = 0
    fields["fold_sharpes"] = tuple(fields["fold_sharpes"])
    fields["fold_net_returns"] = tuple(fields["fold_net_returns"])
    fields["asset_names"] = tuple(fields["asset_names"])
    fields["daily_returns"] = tuple(fields["daily_returns"])
    return ConfigMetrics(**fields)


def neighbor_keys(item: dict) -> list[str]:
    variants = []
    for tf in TF_MINUTES:
        variants.append({**item, "tf": tf})
    for z in Z_VALUES:
        variants.append({**item, "z": z})
    for side in SIDES:
        variants.append({**item, "side": side})
    for exit_mode in EXITS:
        variants.append({**item, "exit": exit_mode})
    keys = {item_key(v["tf"], v["z"], v["side"], v["exit"]) for v in variants}
    keys.discard(item["key"])
    return sorted(k for k in keys if k in ITEMS_BY_KEY)


def neighbor_profitability(item: dict, rows: dict[str, dict]) -> dict:
    keys = neighbor_keys(item)
    evaluated = [rows[k] for k in keys if rows[k]["valid"]]
    profitable = sum(1 for m in evaluated if m["net_return"] > 0)
    denominator = len(evaluated)
    share = profitable / denominator if denominator else 0.0
    return {
        "neighbors_total": len(keys),
        "neighbors_evaluated_valid": denominator,
        "neighbors_profitable": profitable,
        "profitable_share": share,
        "gate_pass": denominator > 0 and share >= NEIGHBOR_MIN_PROFITABLE_SHARE,
    }

# ---------------------------------------------------------------------------
# sweep / finalize


CSV_EXCLUDED = {"daily_returns", "fold_sharpes", "fold_net_returns", "asset_names"}


def _flat_row(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in CSV_EXCLUDED}


def _references(data: MrData) -> dict:
    out = {}
    for name, symbol in (("reference_bh_basket", None), ("reference_bh_btc", "BTCUSDT")):
        rets = []
        symbols = UNIVERSE_SYMBOLS if symbol is None else [symbol]
        d1 = data.series[symbols[0]]["1d"]
        for i, day in enumerate(d1.opens):
            if day < DECIDE_START_MS or day >= DECIDE_END_EXCLUSIVE_MS or i == 0:
                continue
            if symbol is not None:
                rets.append(d1.closes[i] / d1.closes[i - 1] - 1.0)
            else:
                leg = 0.0
                for s in symbols:
                    ser = data.series[s]["1d"]
                    j = bisect.bisect_left(ser.opens, day)
                    leg += ser.closes[j] / ser.closes[j - 1] - 1.0
                rets.append(leg / len(symbols))
        equity = 1.0
        curve = []
        for r in rets:
            equity *= 1.0 + r
            curve.append(equity)
        out[name] = {
            "net_return": equity - 1.0,
            "daily_sharpe": sharpe_ratio(rets),
            "max_drawdown": max_drawdown_from_returns(rets),
        }
    return out


def run_sweep(merged_root: Path, cache_dir: Path) -> dict:
    started = time.time()
    grid = frozen_grid()
    cache_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = cache_dir / "checkpoint-mr-tf-001.json"
    completed: dict[str, dict] = {}
    references: dict[str, dict] = {}
    if checkpoint_path.is_file():
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if (
            payload.get("schema") != SWEEP_SCHEMA
            or payload.get("seed") != SEED_SWEEP
            or payload.get("grid_count") != EXPECTED_GRID_COUNT
            or payload.get("window") != [DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS]
        ):
            raise MrError("resume rejected: MR-TF-001 checkpoint identity mismatch")
        completed = payload.get("rows", {})
        references = payload.get("references", {})
    print(f"MR-TF-001 sweep start: pending={len(grid)-len(completed)}", flush=True)
    if len(completed) < len(grid) or len(references) < 2:
        data = MrData.load(merged_root)
        pending = [i for i in grid if i["key"] not in completed]
        for index, item in enumerate(pending, 1):
            trades = generate_trades(item, data, ROUND_TRIP_COST)
            metrics = config_metrics_row(item, trades)
            completed[item["key"]] = row_from_metrics(item, metrics)
            write_json_atomic(checkpoint_path, {
                "schema": SWEEP_SCHEMA, "seed": SEED_SWEEP, "grid_count": EXPECTED_GRID_COUNT,
                "window": [DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS],
                "rows": completed, "references": references,
            })
            print(f"MR-TF-001 sweep {index}/{len(pending)} done elapsed={time.time()-started:.0f}s", flush=True)
        references = _references(data)
        write_json_atomic(checkpoint_path, {
            "schema": SWEEP_SCHEMA, "seed": SEED_SWEEP, "grid_count": EXPECTED_GRID_COUNT,
            "window": [DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS],
            "rows": completed, "references": references,
        })
    marker = {"expected": EXPECTED_GRID_COUNT, "completed": len(completed), "complete": len(completed) == EXPECTED_GRID_COUNT, "elapsed_seconds": time.time() - started}
    write_json_atomic(cache_dir / "completion-mr-tf-001.json", marker)
    if not marker["complete"]:
        raise MrError("decide sweep incomplete")
    return marker


def heritage_sharpe_variance_mr(extra_values: list[float]) -> dict:
    values = list(extra_values)
    sources = [
        ("005", Path("reports/artifacts/altcoin-multitf-005-phase4/development-metrics.csv")),
        ("006", Path("reports/artifacts/altcoin-multitf-006/development-metrics.csv")),
        ("007", Path("reports/artifacts/altcoin-multitf-007/development-metrics.csv")),
        ("CARRY-001", Path("reports/artifacts/altcoin-carry-001/development-metrics.csv")),
        ("RM-001", Path("reports/artifacts/altcoin-carry-rm-001/development-metrics.csv")),
        ("SL-001", Path("reports/artifacts/altcoin-carry-sl-001/development-metrics.csv")),
        ("FINAL-001", Path("reports/artifacts/altcoin-carry-final-001/development-metrics.csv")),
    ]
    counts = {}
    for name, path in sources:
        count = 0
        with path.open("rt", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                text = (row.get("daily_sharpe") or "").strip()
                if not text:
                    continue
                value = float(text)
                if math.isfinite(value):
                    values.append(value)
                    count += 1
        counts[name] = count
    mean = sum(values) / len(values) if values else 0.0
    var = sum((v - mean) ** 2 for v in values) / len(values) if values else 0.0
    return {"n": len(values), "variance": var, "counts": counts}


def finalize(cache_dir: Path) -> dict:
    started = time.time()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    payload = json.loads((cache_dir / "checkpoint-mr-tf-001.json").read_text(encoding="utf-8"))
    rows = payload["rows"]
    references = payload.get("references", {})
    if len(rows) != EXPECTED_GRID_COUNT:
        raise MrError("unexpected decide row count")
    active_keys = sorted(k for k, r in rows.items() if r["valid"])
    write_json_atomic(ARTIFACTS / "sweep-progress.json", payload)
    sample = next(iter(rows.values()))
    header = sorted(_flat_row(sample))
    with (ARTIFACTS / "development-metrics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for key in sorted(rows):
            flat = _flat_row(rows[key])
            writer.writerow([flat[h] for h in header])
    if not active_keys:
        verdict = {"stage": "FINAL", "decision": "NO_SELECTION", "selected_key": None, "reason": "no active configurations"}
        write_json_atomic(ARTIFACTS / "verdict-final.json", verdict)
        return verdict

    metrics_by_key = {k: metrics_from_row(rows[k]) for k in rows}
    lag = nw_lag(len(rows[active_keys[0]]["daily_returns"]))
    panel = {k: rows[k]["daily_returns"] for k in active_keys}
    spa = spa_pvalues(panel, replicates=SPA_REPLICATES, seed=SEED_SPA, lag=lag)
    naive = {}
    for key in active_keys:
        series = rows[key]["daily_returns"]
        mean = sum(series) / len(series)
        lrv = newey_west_lrv(series, lag)
        stat = None if lrv <= 0 else (len(series) ** 0.5) * mean / (lrv ** 0.5)
        naive[key] = 1.0 if stat is None else 1.0 - min(1.0, max(0.0, normal_cdf(stat)))
    holm = holm_adjusted(naive)
    trials = len(active_keys)
    sr_values = [rows[k]["daily_sharpe"] for k in active_keys if rows[k]["daily_sharpe"] is not None]
    sr_mean = sum(sr_values) / len(sr_values) if sr_values else 0.0
    sr_var = sum((v - sr_mean) ** 2 for v in sr_values) / len(sr_values) if sr_values else 0.0
    dsr = {
        k: deflated_sharpe_probability(rows[k]["daily_sharpe"], rows[k]["daily_returns"], trials, sr_var)
        for k in active_keys
    }
    heritage = heritage_sharpe_variance_mr(sr_values)
    heritage_dsr = {
        k: deflated_sharpe_probability(rows[k]["daily_sharpe"], rows[k]["daily_returns"], HERITAGE_TRIALS, heritage["variance"])
        for k in active_keys
    }
    statistics_payload = {
        k: {
            "spa_p": spa.get(k, 1.0), "naive_p": naive.get(k, 1.0), "holm_p": holm.get(k, 1.0),
            "dsr_probability": dsr.get(k, 0.0), f"heritage_dsr_probability_n{HERITAGE_TRIALS}": heritage_dsr.get(k, 0.0),
        }
        for k in active_keys
    }
    write_json_atomic(ARTIFACTS / "statistics.json", {
        "method": {"spa": "Hansen 2005 screened consistent", "dsr": "Bailey-Lopez de Prado", "holm": "step-down"},
        "spa_replicates": SPA_REPLICATES, "spa_seed": SEED_SPA, "bootstrap_seed": SEED_BOOTSTRAP,
        "n_trials_dsr": trials, "sharpe_variance_across_trials": sr_var, "nw_lag": lag,
        "heritage_report_only": {"n_trials": HERITAGE_TRIALS, **heritage},
        "reference_rows_excluded_from_gates": references,
        "results": statistics_payload,
    })

    eligible = sorted((k for k in active_keys if is_eligible(metrics_by_key[k])), key=lambda k: ordering_key(metrics_by_key[k]))
    write_json_atomic(ARTIFACTS / "eligibility-table.json", {
        "eligible_count": len(eligible),
        "ordering": [{"rank": i + 1, "key": k} for i, k in enumerate(eligible)],
        "table": {k: {
            "episodes_ge_100": rows[k]["trades"] >= 100,
            "positive_net_return": rows[k]["net_return"] > 0,
            "sharpe_above_0_5": rows[k]["annualized_sharpe"] is not None and rows[k]["annualized_sharpe"] > 0.5,
            "drawdown_within_limit": rows[k]["max_drawdown"] >= -0.25,
            "coverage_ge_6_assets": rows[k]["active_assets"] >= 6,
            "concentration_le_40pct": rows[k]["max_asset_positive_share"] <= 0.40,
        } for k in sorted(rows)},
    })

    data = None
    reports = []
    winner = None
    examined = 0
    for key in eligible:
        examined += 1
        m = rows[key]
        st = statistics_payload[key]
        failures = []
        if st["spa_p"] > 0.05:
            failures.append("spa_p_above_limit")
        if st["dsr_probability"] < 0.95:
            failures.append("dsr_below_limit")
        if st["holm_p"] > 0.05:
            failures.append("holm_p_above_limit")
        ncheck = neighbor_profitability(ITEMS_BY_KEY[key], rows)
        if not ncheck["gate_pass"]:
            failures.append("neighbors_share_below_60pct")
        if m["median_fold_sharpe"] <= 0 or m["positive_folds"] < TEMPORAL_MIN_POSITIVE_FOLDS:
            failures.append("temporal_consistency_failed")
        if failures:
            reports.append({"key": key, "failures": failures})
            continue
        if data is None:
            merged_root = Path(r"D:\alt-multitf-005-data\inputs") / "merged"
            data = MrData.load(merged_root)
        boot = circular_block_bootstrap_mean_ci(m["daily_returns"], replicates=BOOTSTRAP_REPLICATES, seed=SEED_BOOTSTRAP)
        stress = {}
        for name, cost in STRESS_COSTS.items():
            trades = generate_trades(ITEMS_BY_KEY[key], data, cost)
            stress[name] = {"net_return": config_metrics_row(ITEMS_BY_KEY[key], trades).net_return, "pass": None}
        for name, mode in (("funding_half", "half"), ("funding_flipped", "flipped")):
            trades = generate_trades(ITEMS_BY_KEY[key], data, ROUND_TRIP_COST, funding_mode=mode)
            stress[name] = {"net_return": config_metrics_row(ITEMS_BY_KEY[key], trades).net_return, "pass": None}
        for name, out in stress.items():
            out["pass"] = out["net_return"] > 0
        maker_trades = generate_trades(ITEMS_BY_KEY[key], data, MAKER_ROUND_TRIP)
        maker_net = config_metrics_row(ITEMS_BY_KEY[key], maker_trades).net_return
        failed_stress = sorted(n for n, o in stress.items() if not o["pass"])
        if boot["lower"] <= 0:
            failures.append("bootstrap_ci_lower_not_positive")
        failures.extend(f"stress_{n}_failed" for n in failed_stress)
        reports.append({
            "key": key, "bootstrap": boot, "stress": stress,
            "maker_track_report_only": {"net_return": maker_net},
            "failures": failures, "passes_all_gates": not failures,
        })
        if not failures and winner is None:
            winner = key
            break
    write_json_atomic(ARTIFACTS / "selection-dossier.json", {
        "tie_break_rule": "pre-registered ordering; rank-1 full passer wins",
        "eligible_candidates": len(eligible), "examined": examined, "reports": reports,
    })
    verdict = {"stage": "FINAL", "decision": "SELECT" if winner else "NO_SELECTION", "selected_key": winner}
    if not winner:
        verdict["consequence"] = "price-flush mean reversion unproven at tested timeframes"
    write_json_atomic(ARTIFACTS / "verdict-final.json", verdict)
    repo_commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    manifest = {
        "protocol_id": PROTOCOL_ID,
        "repo_source_commit": repo_commit,
        "frozen_protocol_document": PROTOCOL_DOC.name,
        "frozen_protocol_sha256": sha256_file(PROTOCOL_DOC),
        "freeze_proof_commit": "db6e4f8",
        "prior_inputs": PRIOR_INPUT_HASHES,
        "downloads": "none",
        "windows_utc": {
            "decide": ["2021-01-01T00:00:00Z", "2026-07-01T00:00:00Z"],
            "monitor_reserve": ["2026-07-01T00:00:00Z", None],
        },
        "universe_used": list(UNIVERSE_SYMBOLS),
        "selection_policy": "single-pass decision; TF pack 2 deferred to its own freeze",
    }
    write_json_atomic(ARTIFACTS / "input-manifest.json", manifest)
    write_json_atomic(ARTIFACTS / "run-metadata.json", {
        "rows": len(rows), "active": len(active_keys),
        "eligible": len(eligible), "examined": examined, "elapsed_seconds": time.time() - started,
        "python": sys.version.split()[0], "seeds": {"sweep": SEED_SWEEP, "bootstrap": SEED_BOOTSTRAP, "spa": SEED_SPA},
    })
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-grid", action="store_true")
    parser.add_argument("--inputs-root", type=Path, default=Path(r"D:\alt-multitf-005-data\inputs"))
    parser.add_argument("--cache-dir", type=Path, default=Path(r"D:\alt-multitf-005-data\mr-tf-001-cache"))
    parser.add_argument("--stage", choices=("sweep", "finalize", "all"), required=False)
    args = parser.parse_args(argv)
    if args.validate_grid:
        grid = frozen_grid()
        print(json.dumps({"count": len(grid), "first_key": grid[0]["key"], "seed": SEED_SWEEP}, sort_keys=True))
        return 0
    merged_root = args.inputs_root / "merged"
    if args.stage in ("sweep", "all"):
        print(json.dumps(run_sweep(merged_root, args.cache_dir), sort_keys=True))
    if args.stage in ("finalize", "all"):
        print(json.dumps(finalize(args.cache_dir), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
