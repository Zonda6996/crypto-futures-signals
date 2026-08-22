from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

PROTOCOL_ID = "ALT-MULTITF-005-PHASE3-FROZEN-1"
DATA_END_MS = 1_767_225_600_000  # 2026-01-01 UTC, exclusive
SEED = 20_260_823
FEE = 0.0005
BASE_SLIPPAGE = 0.0002
STRESS_SLIPPAGE = 0.0005
TF_INTERVALS = {
    "5m": ("6h", "1d"), "15m": ("12h", "1d"), "30m": ("1d", "3d"),
    "1h": ("1d", "3d", "7d"), "2h": ("1d", "3d", "7d"),
    "4h": ("1d", "3d", "7d"), "1d": ("3d", "7d"),
}
LOOKBACKS = (7, 14, 30, 60, 90)
OUTER_FOLDS = tuple((str(year), f"{year}-01-01", f"{year + 1}-01-01") for year in range(2021, 2026))


def canonical_id(config: dict) -> str:
    raw = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:20]


def frozen_manifest() -> dict:
    hypotheses: list[dict] = []
    for tf, intervals in TF_INTERVALS.items():
        for lookback, interval, breadth, weighting, target in product(
            LOOKBACKS, intervals, ("top2", "top4", "top8", "top20pct"),
            ("equal", "inverse_vol", "capped_rank"), (0.10, 0.15, 0.20),
        ):
            config = {"family": "A", "timeframe": tf, "lookback_days": lookback, "rebalance": interval,
                      "breadth": breadth, "weighting": weighting, "volatility_target": target}
            hypotheses.append({"config_id": canonical_id(config), **config})
    for tf, intervals in TF_INTERVALS.items():
        for values in product(LOOKBACKS, intervals, ("next_open", "one_bar_confirmation"),
                              (1.5, 2.0, 3.0), (None, 1.5, 2.0, 3.0),
                              (None, 2.0, 3.0), (1, 3, 7), (0.10, 0.15, 0.20)):
            lookback, interval, entry, stop, take, trailing, time_stop, target = values
            config = {"family": "B", "timeframe": tf, "lookback_days": lookback, "ranking_cycle": interval,
                      "entry": entry, "stop_atr": stop, "take_r": take, "trailing_atr": trailing,
                      "time_stop_days": time_stop, "volatility_target": target}
            hypotheses.append({"config_id": canonical_id(config), **config})
    body = {"protocol_id": PROTOCOL_ID, "created_before_pnl": True, "seed": SEED,
            "development_end_exclusive_ms": DATA_END_MS, "outer_folds": OUTER_FOLDS,
            "execution": {"fee_per_side": FEE, "base_slippage_per_side": BASE_SLIPPAGE,
                          "stress_slippage_per_side": STRESS_SLIPPAGE, "participation": 0.005,
                          "stress_participation": 0.0025, "next_open": True},
            "hypotheses": hypotheses}
    body["manifest_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return body


def write_manifest(path: Path) -> dict:
    doc = frozen_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return doc


def _reject_holdout(path: Path) -> None:
    if "holdout" in str(path).lower():
        raise ValueError("holdout access forbidden")


def load_daily_panel(dataset: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    _reject_holdout(dataset)
    roster = json.loads((dataset / "metadata/roster.snapshot.json").read_text())["symbols"]
    closes: dict[str, pd.Series] = {}
    opens: dict[str, pd.Series] = {}
    funding: dict[str, pd.Series] = {}
    for symbol in roster:
        bar_path = dataset / f"development/normalized/klines/{symbol}/{symbol}-1d.csv.gz"
        if bar_path.exists():
            frame = pd.read_csv(bar_path, compression="gzip", usecols=["open_time_ms", "open", "close"])
            if (frame.open_time_ms >= DATA_END_MS).any():
                frame = frame[frame.open_time_ms < DATA_END_MS]
            idx = pd.to_datetime(frame.open_time_ms, unit="ms", utc=True).dt.floor("D")
            closes[symbol] = pd.Series(frame.close.to_numpy(float), index=idx)
            opens[symbol] = pd.Series(frame.open.to_numpy(float), index=idx)
        funding_path = dataset / f"development/normalized/funding/{symbol}/{symbol}-funding.csv.gz"
        if funding_path.exists():
            ff = pd.read_csv(funding_path, compression="gzip", usecols=["funding_time_ms", "funding_rate"])
            ff = ff[ff.funding_time_ms < DATA_END_MS]
            idx = pd.to_datetime(ff.funding_time_ms, unit="ms", utc=True).dt.floor("D")
            funding[symbol] = pd.Series(ff.funding_rate.to_numpy(float), index=idx).groupby(level=0).sum()
    close = pd.DataFrame(closes).sort_index()
    opened = pd.DataFrame(opens).reindex(close.index)
    funds = pd.DataFrame(funding).reindex(close.index).fillna(0.0)
    if close.empty or close.index.max() >= pd.Timestamp("2026-01-01", tz="UTC"):
        raise ValueError("development boundary violation")
    return close, opened, funds


def _breadth(name: str, count: int) -> int:
    return max(2, math.ceil(0.2 * count)) if name == "top20pct" else int(name[3:])


def _weights(momentum: pd.Series, vol: pd.Series, method: str, breadth: str) -> pd.Series:
    ranked = momentum[momentum > 0].dropna().sort_values(ascending=False)
    selected = ranked.iloc[:_breadth(breadth, len(ranked))]
    if selected.empty:
        return pd.Series(0.0, index=momentum.index)
    if method == "inverse_vol":
        raw = 1.0 / vol.reindex(selected.index).replace(0, np.nan)
    elif method == "capped_rank":
        raw = pd.Series(np.arange(len(selected), 0, -1, dtype=float), index=selected.index)
    else:
        raw = pd.Series(1.0, index=selected.index)
    raw = raw.replace([np.inf, -np.inf], np.nan).dropna()
    raw = raw / raw.sum() if raw.sum() else raw * 0
    if method == "capped_rank":
        # Deterministic iterative redistribution under the frozen 20% symbol cap.
        for _ in range(20):
            excess = (raw - 0.20).clip(lower=0).sum()
            raw = raw.clip(upper=0.20)
            free = raw[raw < 0.20]
            if excess <= 1e-12 or free.empty: break
            raw.loc[free.index] += excess * free / free.sum()
    return raw.reindex(momentum.index).fillna(0.0).clip(upper=0.20)


def metrics(returns: pd.Series, turnover: pd.Series, costs: pd.Series, funding: pd.Series) -> dict:
    returns = returns.fillna(0.0)
    equity = (1.0 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    sigma = returns.std(ddof=0)
    sharpe = float(returns.mean() / sigma * np.sqrt(365)) if sigma > 0 else 0.0
    downside = returns[returns < 0].std(ddof=0)
    sortino = float(returns.mean() / downside * np.sqrt(365)) if downside and downside > 0 else 0.0
    years = len(returns) / 365
    annual = float(equity.iloc[-1] ** (1 / years) - 1) if years > 0 and equity.iloc[-1] > 0 else -1.0
    max_dd = float(drawdown.min()) if len(drawdown) else 0.0
    return {"observations": len(returns), "compounded_net_return": float(equity.iloc[-1] - 1) if len(equity) else 0.0,
            "annualized_return": annual, "sharpe": sharpe, "sortino": sortino,
            "calmar": annual / abs(max_dd) if max_dd < 0 else 0.0, "max_drawdown": max_dd,
            "turnover": float(turnover.sum()), "cost_drag": float(costs.sum()),
            "funding_return": float(funding.sum()), "active_days": int((turnover > 0).sum())}


def evaluate_a(config: dict, close: pd.DataFrame, opened: pd.DataFrame, funds: pd.DataFrame,
               slippage: float = BASE_SLIPPAGE, extra_delay: int = 0) -> tuple[dict, pd.DataFrame]:
    lookback = config["lookback_days"]
    momentum = close.pct_change(lookback, fill_method=None)
    daily_ret = opened.shift(-1).div(opened).sub(1.0)
    realized = close.pct_change(fill_method=None).rolling(30, min_periods=30).std(ddof=0) * np.sqrt(365)
    interval = config["rebalance"]
    hours = int(interval[:-1]) if interval.endswith("h") else int(interval[:-1]) * 24
    step_days = max(1, math.ceil(hours / 24))
    # Compute only rebalance rows, then causally carry positions forward.
    # This is equivalent to the former day-by-day loop but much faster.
    decision_rows = np.arange(0, max(0, len(close.index) - 1), step_days)
    decision_index = close.index[decision_rows]
    decisions = pd.DataFrame(0.0, index=decision_index, columns=close.columns)
    for date in decision_index:
        target = _weights(momentum.loc[date], realized.loc[date], config["weighting"], config["breadth"])
        selected_vol = realized.loc[date].reindex(target[target > 0].index).dropna()
        forecast = float((selected_vol * target.reindex(selected_vol.index)).sum()) if not selected_vol.empty else np.nan
        scale = min(1.0, config["volatility_target"] / forecast) if forecast and np.isfinite(forecast) else 0.0
        decisions.loc[date] = target * scale
    weights = decisions.reindex(close.index).ffill().fillna(0.0)
    execution_weights = weights.shift(1 + extra_delay).fillna(0.0)
    gross = (execution_weights * daily_ret.fillna(0.0)).sum(axis=1)
    funding_ret = -(execution_weights * funds.fillna(0.0)).sum(axis=1)
    turn = execution_weights.diff().abs().sum(axis=1).fillna(execution_weights.abs().sum(axis=1))
    cost = turn * (FEE + slippage)
    net = gross + funding_ret - cost
    ledger = pd.DataFrame({"net_return": net, "gross_return": gross, "funding_return": funding_ret,
                           "turnover": turn, "cost": cost, "gross_exposure": execution_weights.sum(axis=1)})
    violation = int((execution_weights < -1e-12).any().any() or (execution_weights.sum(axis=1) > 1.0000001).any()
                    or (execution_weights.max(axis=1) > 0.2000001).any())
    result = {**config, **metrics(net, turn, cost, funding_ret), "hard_violation_count": violation}
    return result, ledger


def run(dataset: Path, output: Path, limit: int | None = None) -> dict:
    manifest_path = output / "frozen-manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else write_manifest(manifest_path)
    close, opened, funds = load_daily_panel(dataset)
    configs = [h for h in manifest["hypotheses"] if h["family"] == "A"]
    if limit is not None: configs = configs[:limit]
    rows: list[dict] = []
    fold_rows: list[dict] = []
    best_key: tuple[float, float] | None = None
    best_ledger: pd.DataFrame | None = None
    replay_cache: dict[tuple, tuple[dict, pd.DataFrame, dict]] = {}
    for n, config in enumerate(configs, 1):
        interval = config["rebalance"]
        hours = int(interval[:-1]) if interval.endswith("h") else int(interval[:-1]) * 24
        effective_key = (config["lookback_days"], max(1, math.ceil(hours / 24)), config["breadth"],
                         config["weighting"], config["volatility_target"])
        if effective_key not in replay_cache:
            cached_base, cached_ledger = evaluate_a(config, close, opened, funds)
            cached_stress, _ = evaluate_a(config, close, opened, funds, STRESS_SLIPPAGE)
            replay_cache[effective_key] = (cached_base, cached_ledger, cached_stress)
        cached_base, ledger, cached_stress = replay_cache[effective_key]
        base = {**config, **{key: value for key, value in cached_base.items() if key not in config}}
        stress = {**config, **{key: value for key, value in cached_stress.items() if key not in config}}
        folds = []
        for fold, start, end in OUTER_FOLDS:
            fold_start = pd.Timestamp(start, tz="UTC")
            fold_end = pd.Timestamp(end, tz="UTC") - pd.Timedelta(days=1)
            part = ledger.loc[fold_start:fold_end]
            fm = metrics(part.net_return, part.turnover, part.cost, part.funding_return)
            fold_rows.append({"config_id": config["config_id"], "fold": fold, **fm})
            folds.append(fm)
        row = {**base, "stress_compounded_net_return": stress["compounded_net_return"], "stress_sharpe": stress["sharpe"],
               "positive_outer_fold_share": sum(x["compounded_net_return"] > 0 for x in folds) / len(folds),
               "median_outer_sharpe": float(np.median([x["sharpe"] for x in folds])),
               "median_outer_calmar": float(np.median([x["calmar"] for x in folds]))}
        rows.append(row)
        selection_key = (row["median_outer_sharpe"], row["compounded_net_return"])
        if best_key is None or selection_key > best_key:
            best_key = selection_key
            best_ledger = ledger.copy()
        if n % 100 == 0: print(f"evaluated {n}/{len(configs)}", flush=True)
    board = pd.DataFrame(rows).sort_values(["median_outer_sharpe", "compounded_net_return"], ascending=False)
    output.mkdir(parents=True, exist_ok=True)
    board.to_csv(output / "leaderboard-family-a.csv", index=False)
    pd.DataFrame(fold_rows).to_csv(output / "per-fold-family-a.csv", index=False)
    best = board.iloc[0].to_dict() if len(board) else None
    if best and best_ledger is not None:
        best_ledger.to_csv(output / "winner-family-a-ledger.csv")
    verdict = {"protocol_id": PROTOCOL_ID, "manifest_sha256": manifest["manifest_sha256"],
               "evaluated_family_a": len(rows), "manifest_family_a": sum(h["family"] == "A" for h in manifest["hypotheses"]),
               "evaluated_family_b": 0, "manifest_family_b": sum(h["family"] == "B" for h in manifest["hypotheses"]),
               "family_a_best": best, "verdict": "NO WINNER",
               "reason": "Family B and mandatory statistical/robustness gates are not complete; no strategy may be promoted."}
    (output / "verdict.json").write_text(json.dumps(verdict, indent=2, sort_keys=True, default=str) + "\n")
    return verdict


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    manifest_cmd = sub.add_parser("manifest"); manifest_cmd.add_argument("--output", type=Path, default=Path("reports/artifacts/altcoin-multitf-005-phase3/frozen-manifest.json"))
    run_cmd = sub.add_parser("run"); run_cmd.add_argument("--dataset", type=Path, required=True); run_cmd.add_argument("--output", type=Path, default=Path("reports/artifacts/altcoin-multitf-005-phase3")); run_cmd.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.command == "manifest":
        print(json.dumps(write_manifest(args.output), sort_keys=True))
    else:
        print(json.dumps(run(args.dataset, args.output, args.limit), sort_keys=True, default=str))


if __name__ == "__main__": main()
