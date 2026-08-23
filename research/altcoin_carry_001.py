"""ALTCOIN_CARRY_001 deterministic sweep runner (H-CARRY funding carry).

Implements the frozen protocol `docs/ALTCOIN_CARRY_001_FROZEN_PROTOCOL.md`: a
dollar-neutral cross-sectional funding-carry portfolio on the ten frozen universe
perpetuals. Signals use only past funding rates; target weights are set at a day's
close and govern the next day's price and funding returns; proportional costs are
charged on traded notional at each rebalance. Statistical machinery (SPA, Holm, DSR,
heritage report, block bootstrap, neighbour topology, stress scenarios, eleven
calendar half-year folds identical to ALT-MULTITF-007) is reused unchanged.

The monitor reserve (2026-07..) is never read by this module.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

from research.altcoin_multitf_inputs import UNIVERSE_SYMBOLS
from research.altcoin_multitf_phase3 import write_json_atomic
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

PROTOCOL_ID = "ALTCOIN_CARRY-001"
PROTOCOL_DOC = Path("docs/ALTCOIN_CARRY_001_FROZEN_PROTOCOL.md")
ARTIFACTS = Path("reports/artifacts/altcoin-carry-001")
SUPPLEMENT_ROOT = "altcoin-multitf-006-supplement"

DAY_MS = 86_400_000
ANNUALIZATION_SQRT = 365.0 ** 0.5

SEED_SWEEP = 20260914
SEED_BOOTSTRAP = 20260915
SEED_SPA = 20260916

LOOKBACK_DAYS = (1, 3, 7)
K_PER_SIDE = (2, 3)
REBAL_DAYS = (1, 7)
EXPECTED_GRID_COUNT = 12

PRIMARY_TRADE_COST = 6.0e-4   # fee 4 bps + slippage 2 bps per unit traded notional
MAKER_TRADE_COST = 3.0e-4     # fee 2 bps + slippage 1 bps, report-only track
STRESS_TRADE_COSTS = {
    "fee_double": 8.0e-4 + 2.0e-4,
    "slippage_triple": 4.0e-4 + 6.0e-4,
}

SPA_REPLICATES = 1000
BOOTSTRAP_REPLICATES = 2000
SHORTLIST_SIZE = 12

HERITAGE_TRIALS = 5_832 + 192 + 8 + 12  # every configuration ever evaluated: 005+006+007+CARRY-001
TEMPORAL_MIN_POSITIVE_FOLDS = 7
NEIGHBOR_MIN_PROFITABLE_SHARE = 0.60
ELIGIBILITY_MIN_EPISODES = 100
ELIGIBILITY_MIN_SHARPE = 0.5
ELIGIBILITY_MAX_DRAWDOWN = -0.25
ELIGIBILITY_MIN_ACTIVE_ASSETS = 6
CONCENTRATION_LIMIT = 0.40

SWEEP_SCHEMA = "altcoin-carry-001-sweep-v1"

PRIOR_INPUT_HASHES = {
    "primary_archive_sha256": "665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d",
    "supplement_archive_sha256": "a753585a11beb7bad74f9262920324fe8315a681b6dd108db072790bad47bd5b",
    "supplement_v2_archive_sha256": "487046fad5659e427075ca2b2b676bb3213da85276848129ba5eb21f00d10c56",
}


class CarryError(RuntimeError):
    pass


def frozen_grid() -> tuple[dict, ...]:
    grid = []
    keys = set()
    for lookback in LOOKBACK_DAYS:
        for k in K_PER_SIDE:
            for rebal in REBAL_DAYS:
                config = {"lookback_days": lookback, "k_per_side": k, "rebal_days": rebal}
                key = config_key(config)
                if key in keys:
                    raise CarryError(f"configuration key collision: {key}")
                keys.add(key)
                grid.append(config)
    grid.sort(key=config_key)
    if len(grid) != EXPECTED_GRID_COUNT:
        raise CarryError(f"frozen CARRY-001 grid mismatch: {len(grid)} != {EXPECTED_GRID_COUNT}")
    return tuple(grid)


def config_key(config: dict) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


# ---------------------------------------------------------------------------
# data


def _read_daily_closes(path: Path, end_exclusive_ms: int) -> dict[int, float]:
    if not path.is_file():
        raise CarryError(f"missing normalized series: {path}")
    closes: dict[int, float] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            open_ms = int(row["open_time_ms"])
            if open_ms >= end_exclusive_ms:
                continue
            closes[open_ms] = float(row["close"])
    if not closes:
        raise CarryError(f"empty series: {path}")
    return closes


def _read_funding_by_day(path: Path, end_exclusive_ms: int) -> tuple[dict[int, float], dict[int, int], int]:
    if not path.is_file():
        raise CarryError(f"missing funding series: {path}")
    by_day: dict[int, float] = {}
    counts: dict[int, int] = {}
    first_ts = None
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            ts = int(row["funding_time_ms"])
            if ts >= end_exclusive_ms:
                continue
            if first_ts is None or ts < first_ts:
                first_ts = ts
            day = ts - ts % DAY_MS
            by_day[day] = by_day.get(day, 0.0) + float(row["funding_rate"])
            counts[day] = counts.get(day, 0) + 1
    if first_ts is None:
        raise CarryError(f"empty funding series: {path}")
    return by_day, counts, first_ts


class CarryData:
    """Daily closes and per-day funding sums/counts for the frozen universe."""

    def __init__(
        self,
        closes: dict[str, dict[int, float]],
        funding_by_day: dict[str, dict[int, float]],
        funding_counts_by_day: dict[str, dict[int, int]],
        funding_first_ts: dict[str, int],
    ) -> None:
        self.closes = closes
        self.funding_by_day = funding_by_day
        self.funding_counts_by_day = funding_counts_by_day
        self.funding_first_ts = funding_first_ts

    @classmethod
    def load(cls, merged_root: Path) -> "CarryData":
        base = merged_root.resolve() / SUPPLEMENT_ROOT / "development" / "normalized"
        end = DECIDE_END_EXCLUSIVE_MS
        closes, funding, counts, firsts = {}, {}, {}, {}
        for symbol in UNIVERSE_SYMBOLS:
            closes[symbol] = _read_daily_closes(base / "klines" / symbol / f"{symbol}-1d.csv.gz", end)
            funding[symbol], counts[symbol], firsts[symbol] = _read_funding_by_day(
                base / "funding" / symbol / f"{symbol}-funding.csv.gz", end
            )
        return cls(closes, funding, counts, firsts)

    def day_is_complete(self, day: int) -> bool:
        previous = day - DAY_MS
        return all(
            day in self.closes[s] and previous in self.closes[s] for s in UNIVERSE_SYMBOLS
        )

    def price_return(self, symbol: str, day: int) -> float:
        return self.closes[symbol][day] / self.closes[symbol][day - DAY_MS] - 1.0

    def funding_sum(self, symbol: str, day: int) -> float:
        return self.funding_by_day[symbol].get(day, 0.0)

    def signal(self, symbol: str, day: int, lookback: int) -> float | None:
        window_start = day - (lookback - 1) * DAY_MS
        if self.funding_first_ts.get(symbol, 1 << 62) > window_start:
            return None
        total = 0.0
        count = 0
        sums = self.funding_by_day[symbol]
        nums = self.funding_counts_by_day[symbol]
        offset = 0
        while offset < lookback:
            bucket = window_start + offset * DAY_MS
            total += sums.get(bucket, 0.0)
            count += nums.get(bucket, 0)
            offset += 1
        if count == 0:
            return None
        return total / count


def simulate(config: dict, data: CarryData, trade_cost: float, *, stress_funding: str | None = None) -> dict:
    lookback, k, rebal = config["lookback_days"], config["k_per_side"], config["rebal_days"]
    weight = 1.0 / (2.0 * k)

    days = [day for day in range(DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS, DAY_MS)]
    equity = 1.0
    fractions = {s: 0.0 for s in UNIVERSE_SYMBOLS}
    daily_returns: list[float] = []
    episode_count = 0
    active: set[str] = set()
    symbol_pnl = {s: 0.0 for s in UNIVERSE_SYMBOLS}

    for index, day in enumerate(days):
        if not data.day_is_complete(day):
            daily_returns.append(0.0)
            continue
        price_term = 0.0
        funding_term = 0.0
        for symbol in UNIVERSE_SYMBOLS:
            rpx = data.price_return(symbol, day)
            f = data.funding_sum(symbol, day)
            if stress_funding == "half":
                f *= 0.5
            elif stress_funding == "flipped":
                f = -f
            w = fractions[symbol]
            price_term += w * rpx
            funding_term -= w * f
            symbol_pnl[symbol] += w * rpx - w * f
        growth = 1.0 + price_term + funding_term
        if not growth > 0:
            return invalid_result(config, "equity_non_positive")
        for symbol in UNIVERSE_SYMBOLS:
            rpx = data.price_return(symbol, day)
            fractions[symbol] = fractions[symbol] * (1.0 + rpx) / growth
        cost_multiplier = 1.0
        if index % rebal == 0:
            signals = {s: data.signal(s, day, lookback) for s in UNIVERSE_SYMBOLS}
            if all(value is not None for value in signals.values()):
                ranked = sorted(UNIVERSE_SYMBOLS, key=lambda s: (-signals[s], s))
                shorts = set(ranked[:k])
                longs = set(ranked[len(ranked) - k:])
                turnover = 0.0
                for symbol in UNIVERSE_SYMBOLS:
                    target = -weight if symbol in shorts else weight if symbol in longs else 0.0
                    turnover += abs(target - fractions[symbol])
                    fractions[symbol] = target
                cost_multiplier = max(0.0, 1.0 - trade_cost * turnover)
                episode_count += 2 * k
                active.update(shorts)
                active.update(longs)
        previous_equity = equity
        equity = previous_equity * growth * cost_multiplier
        daily_returns.append(equity / previous_equity - 1.0)
    return {
        "config": dict(config),
        "key": config_key(config),
        "valid": True,
        "invalid_reason": None,
        "net_equity": equity,
        "daily_returns": daily_returns,
        "episodes": episode_count,
        "active_assets": len(active),
        "asset_names": sorted(active),
        "symbol_pnl": symbol_pnl,
        "final_fractions": dict(fractions),
    }


def invalid_result(config: dict, reason: str) -> dict:
    return {
        "config": dict(config),
        "key": config_key(config),
        "valid": False,
        "invalid_reason": reason,
        "net_equity": 1.0,
        "daily_returns": [],
        "episodes": 0,
        "active_assets": 0,
        "asset_names": [],
        "symbol_pnl": {},
    }


# ---------------------------------------------------------------------------
# metrics and gates


def _fold_day_positions() -> list[tuple[int, int]]:
    total_days = (DECIDE_END_EXCLUSIVE_MS - DECIDE_START_MS) // DAY_MS
    positions = []
    for start_ms, end_ms in FOLD_BOUNDS_007:
        first = (start_ms - DECIDE_START_MS) // DAY_MS
        last = (end_ms - DECIDE_START_MS) // DAY_MS
        positions.append((first, min(last, total_days)))
    return positions


FOLD_POSITIONS = _fold_day_positions()


def max_drawdown_from_returns(returns: list[float]) -> float:
    peak = 1.0
    equity = 1.0
    worst = 0.0
    for value in returns:
        equity *= 1.0 + value
        if equity > peak:
            peak = equity
        if peak > 0:
            drawdown = equity / peak - 1.0
            if drawdown < worst:
                worst = drawdown
    return worst


def config_metrics(key: str, config: dict, result: dict) -> dict:
    returns = result["daily_returns"]
    daily_sharpe = sharpe_ratio(returns)
    fold_sharpes = []
    for first, last in FOLD_POSITIONS:
        segment = returns[first:last]
        value = sharpe_ratio(segment)
        fold_sharpes.append(0.0 if value is None else value * ANNUALIZATION_SQRT)
    positive_pnl = sum(v for v in result["symbol_pnl"].values() if v > 0)
    max_share = (
        max((v for v in result["symbol_pnl"].values() if v > 0), default=0.0) / positive_pnl
        if positive_pnl > 0
        else 1.0
    )
    return {
        "key": key,
        "config": dict(config),
        "valid": result["valid"],
        "invalid_reason": result["invalid_reason"],
        "episodes": result["episodes"],
        "net_equity": result["net_equity"],
        "net_return": result["net_equity"] - 1.0,
        "daily_sharpe": daily_sharpe,
        "annualized_sharpe": None if daily_sharpe is None else daily_sharpe * ANNUALIZATION_SQRT,
        "median_fold_sharpe": sorted(fold_sharpes)[len(fold_sharpes) // 2] if fold_sharpes else 0.0,
        "fold_sharpes": fold_sharpes,
        "positive_folds": sum(1 for v in fold_sharpes if v > 0),
        "max_drawdown": max_drawdown_from_returns(returns),
        "active_assets": result["active_assets"],
        "asset_names": result["asset_names"],
        "max_asset_positive_share": max_share,
        "daily_returns": returns,
    }


def is_eligible(metrics: dict) -> bool:
    if not metrics["valid"]:
        return False
    sharpe_ok = metrics["annualized_sharpe"] is not None and metrics["annualized_sharpe"] > ELIGIBILITY_MIN_SHARPE
    return all([
        metrics["episodes"] >= ELIGIBILITY_MIN_EPISODES,
        metrics["net_return"] > 0,
        sharpe_ok,
        metrics["max_drawdown"] >= ELIGIBILITY_MAX_DRAWDOWN,
        metrics["active_assets"] >= ELIGIBILITY_MIN_ACTIVE_ASSETS,
        metrics["episodes"] > 0 and metrics["max_asset_positive_share"] <= CONCENTRATION_LIMIT,
    ])


def ordering_key(metrics: dict) -> tuple:
    aggregate = metrics["annualized_sharpe"] if metrics["annualized_sharpe"] is not None else float("-inf")
    return (
        0 if is_eligible(metrics) else 1,
        -metrics["median_fold_sharpe"],
        -aggregate,
        -metrics["net_return"],
        -metrics["max_drawdown"],
        metrics["key"],
    )


def neighbor_keys(config: dict) -> list[dict]:
    variants = []
    for lookback in LOOKBACK_DAYS:
        variants.append({**config, "lookback_days": lookback})
    for k in K_PER_SIDE:
        variants.append({**config, "k_per_side": k})
    for rebal in REBAL_DAYS:
        variants.append({**config, "rebal_days": rebal})
    keys = {config_key(v): v for v in variants}
    keys.pop(config_key(config), None)
    return [keys[k] for k in sorted(keys)]


def neighbor_profitability(config: dict, metrics_by_key: dict[str, dict]) -> dict:
    evaluated = []
    for variant in neighbor_keys(config):
        metrics = metrics_by_key.get(config_key(variant))
        if metrics is not None and metrics["valid"]:
            evaluated.append(metrics)
    profitable = sum(1 for m in evaluated if m["net_return"] > 0)
    denominator = len(evaluated)
    share = profitable / denominator if denominator else 0.0
    return {
        "neighbors_total": len(neighbor_keys(config)),
        "neighbors_evaluated_valid": denominator,
        "neighbors_profitable": profitable,
        "profitable_share": share,
        "gate_pass": denominator > 0 and share >= NEIGHBOR_MIN_PROFITABLE_SHARE,
    }


# ---------------------------------------------------------------------------
# sweep / finalize


CSV_EXCLUDED = {"daily_returns", "fold_sharpes", "asset_names", "config"}


def run_sweep(merged_root: Path, cache_dir: Path) -> dict:
    started = time.time()
    grid = frozen_grid()
    cache_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = cache_dir / "checkpoint-carry-001.json"
    completed: dict[str, dict] = {}
    if checkpoint_path.is_file():
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if (
            payload.get("schema") != SWEEP_SCHEMA
            or payload.get("seed") != SEED_SWEEP
            or payload.get("grid_count") != EXPECTED_GRID_COUNT
            or payload.get("window") != [DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS]
        ):
            raise CarryError("resume rejected: CARRY-001 checkpoint identity mismatch")
        completed = payload.get("rows", {})
    print(f"CARRY-001 sweep start: pending={len(grid)-len(completed)}", flush=True)
    if len(completed) < len(grid):
        data = CarryData.load(merged_root)
        pending = [c for c in grid if config_key(c) not in completed]
        for index, config in enumerate(pending, 1):
            result = simulate(config, data, PRIMARY_TRADE_COST)
            metrics = config_metrics(config_key(config), config, result)
            completed[config_key(config)] = metrics
            write_json_atomic(checkpoint_path, {
                "schema": SWEEP_SCHEMA, "seed": SEED_SWEEP, "grid_count": EXPECTED_GRID_COUNT,
                "window": [DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS], "rows": completed,
            })
            print(f"CARRY-001 sweep {index}/{len(pending)} done elapsed={time.time()-started:.0f}s", flush=True)
    marker = {"expected": EXPECTED_GRID_COUNT, "completed": len(completed), "complete": len(completed) == EXPECTED_GRID_COUNT, "elapsed_seconds": time.time() - started}
    write_json_atomic(cache_dir / "completion-carry-001.json", marker)
    if not marker["complete"]:
        raise CarryError("decide sweep incomplete")
    return marker


def load_rows(cache_dir: Path) -> dict[str, dict]:
    payload = json.loads((cache_dir / "checkpoint-carry-001.json").read_text(encoding="utf-8"))
    rows = payload["rows"]
    if len(rows) != EXPECTED_GRID_COUNT:
        raise CarryError("unexpected decide row count")
    return rows


def input_manifest(repo_commit: str) -> dict:
    manifest = {
        "protocol_id": PROTOCOL_ID,
        "repo_source_commit": repo_commit,
        "frozen_protocol_document": PROTOCOL_DOC.name,
        "frozen_protocol_sha256": sha256_file(PROTOCOL_DOC),
        "freeze_proof_commit": "26b78ca",
        "prior_inputs": PRIOR_INPUT_HASHES,
        "provenance_note": "input archives verified against frozen hashes by ALT-MULTITF-007 execution; no new downloads",
        "windows_utc": {
            "decide": ["2021-01-01T00:00:00Z", "2026-07-01T00:00:00Z"],
            "monitor_reserve": ["2026-07-01T00:00:00Z", None],
        },
        "universe_used": list(UNIVERSE_SYMBOLS),
        "selection_policy": "single-pass decision; hypothesis-level NO_SELECTION only",
    }
    write_json_atomic(ARTIFACTS / "input-manifest.json", manifest)
    return manifest


def heritage_sharpe_variance(extra_values: list[float]) -> dict:
    """Published per-configuration daily Sharpes of 005+006+007 plus current values."""
    values = list(extra_values)
    sources = [
        ("005", Path("reports/artifacts/altcoin-multitf-005-phase4/development-metrics.csv")),
        ("006", Path("reports/artifacts/altcoin-multitf-006/development-metrics.csv")),
        ("007", Path("reports/artifacts/altcoin-multitf-007/development-metrics.csv")),
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


def finalize(cache_dir: Path, merged_root: Path) -> dict:
    started = time.time()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    rows = load_rows(cache_dir)
    grid = list(frozen_grid())
    invalid = [k for k, r in rows.items() if not r["valid"]]
    active_keys = sorted(k for k, r in rows.items() if r["valid"])
    write_json_atomic(ARTIFACTS / "sweep-progress.json", json.loads((cache_dir / "checkpoint-carry-001.json").read_text(encoding="utf-8")))
    csv_excluded = {"daily_returns", "fold_sharpes", "asset_names", "config"}
    sample = next(iter(rows.values()))
    header = sorted({**sample["config"], **{k: v for k, v in sample.items() if k not in csv_excluded}})
    with (ARTIFACTS / "development-metrics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for key in sorted(rows):
            row = rows[key]
            flat = {**row["config"], **{k: v for k, v in row.items() if k not in csv_excluded}}
            writer.writerow([flat[h] for h in header])
    if not active_keys:
        verdict = {"stage": "FINAL", "decision": "NO_SELECTION", "selected_key": None, "reason": "no active configurations"}
        write_json_atomic(ARTIFACTS / "verdict-final.json", verdict)
        return verdict

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
    heritage = heritage_sharpe_variance(sr_values)
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
        "results": statistics_payload,
    })

    eligible = sorted((k for k in active_keys if is_eligible(rows[k])), key=lambda k: ordering_key(rows[k]))
    write_json_atomic(ARTIFACTS / "eligibility-table.json", {
        "eligible_count": len(eligible),
        "ordering": [{"rank": i + 1, "key": k} for i, k in enumerate(eligible[:SHORTLIST_SIZE])],
        "table": {
            k: {
                "episodes_ge_100": rows[k]["episodes"] >= ELIGIBILITY_MIN_EPISODES,
                "positive_net_return": rows[k]["net_return"] > 0,
                "sharpe_above_0_5": rows[k]["annualized_sharpe"] is not None and rows[k]["annualized_sharpe"] > ELIGIBILITY_MIN_SHARPE,
                "drawdown_within_limit": rows[k]["max_drawdown"] >= ELIGIBILITY_MAX_DRAWDOWN,
                "coverage_ge_6_assets": rows[k]["active_assets"] >= ELIGIBILITY_MIN_ACTIVE_ASSETS,
                "concentration_le_40pct": rows[k]["max_asset_positive_share"] <= CONCENTRATION_LIMIT,
            }
            for k in sorted(rows)
        },
    })

    data = None
    reports = []
    winner = None
    examined = 0
    for key in eligible[:SHORTLIST_SIZE]:
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
        ncheck = neighbor_profitability(m["config"], rows)
        if not ncheck["gate_pass"]:
            failures.append("neighbors_share_below_60pct")
        if m["median_fold_sharpe"] <= 0 or m["positive_folds"] < TEMPORAL_MIN_POSITIVE_FOLDS:
            failures.append("temporal_consistency_failed")
        if failures:
            reports.append({"key": key, "failures": failures})
            continue
        if data is None:
            data = CarryData.load(merged_root)
        boot = circular_block_bootstrap_mean_ci(m["daily_returns"], replicates=BOOTSTRAP_REPLICATES, seed=SEED_BOOTSTRAP)
        stress = {}
        for name, cost in STRESS_TRADE_COSTS.items():
            net = simulate(m["config"], data, cost)["net_equity"] - 1.0
            stress[name] = {"net_return": net, "pass": net > 0}
        for name, mode in (("funding_half", "half"), ("funding_flipped", "flipped")):
            net = simulate(m["config"], data, PRIMARY_TRADE_COST, stress_funding=mode)["net_equity"] - 1.0
            stress[name] = {"net_return": net, "pass": net > 0}
        maker_net = simulate(m["config"], data, MAKER_TRADE_COST)["net_equity"] - 1.0
        if boot["lower"] <= 0:
            failures.append("bootstrap_ci_lower_not_positive")
        failures.extend(f"stress_{n}_failed" for n, o in sorted(stress.items()) if not o["pass"])
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
        verdict["consequence"] = "H-CARRY hypothesis unproven on this data"
    write_json_atomic(ARTIFACTS / "verdict-final.json", verdict)
    write_json_atomic(ARTIFACTS / "run-metadata.json", {
        "rows": len(rows), "invalid": len(invalid), "active": len(active_keys),
        "eligible": len(eligible), "examined": examined, "elapsed_seconds": time.time() - started,
        "python": sys.version.split()[0], "seeds": {"sweep": SEED_SWEEP, "bootstrap": SEED_BOOTSTRAP, "spa": SEED_SPA},
    })
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-grid", action="store_true")
    parser.add_argument("--inputs-root", type=Path, default=Path(r"D:\alt-multitf-005-data\inputs"))
    parser.add_argument("--cache-dir", type=Path, default=Path(r"D:\alt-multitf-005-data\carry001-cache"))
    parser.add_argument("--stage", choices=("sweep", "finalize", "all"), required=False)
    args = parser.parse_args(argv)
    if args.validate_grid:
        grid = frozen_grid()
        print(json.dumps({"count": len(grid), "first_key": config_key(grid[0]), "seed": SEED_SWEEP}, sort_keys=True))
        return 0
    merged_root = args.inputs_root / "merged"
    repo_commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    if args.stage in ("sweep", "all"):
        print(json.dumps(run_sweep(merged_root, args.cache_dir), sort_keys=True))
    if args.stage in ("finalize", "all"):
        input_manifest(repo_commit)
        print(json.dumps(finalize(args.cache_dir, merged_root), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
