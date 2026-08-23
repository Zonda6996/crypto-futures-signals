"""ALTCOIN_CARRY_RM_001 deterministic sweep runner (risk-managed funding carry).

Implements the frozen protocol `docs/ALTCOIN_CARRY_RM_001_FROZEN_PROTOCOL.md`: the
CARRY-001 simulator contract with one addition — a causal drawdown de-risking overlay.
At each day's close the portfolio's drawdown from its running peak (computed on the
provisional pre-cost equity, see frozen erratum) maps linearly to a gross-exposure
multiplier between dd_start and dd_stop; all fractions rescale immediately and pay
standard turnover costs. Two carry cores from published CARRY-001 diagnostics; two
bare-core reference rows are emitted outside the grid for comparability only.

The monitor reserve (2026-07..) is never read by this module.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

from research.altcoin_carry_001 import (
    CarryData,
    CarryError,
    DAY_MS,
    MAKER_TRADE_COST,
    PRIMARY_TRADE_COST,
    STRESS_TRADE_COSTS,
    config_metrics,
    heritage_sharpe_variance,
    is_eligible,
    max_drawdown_from_returns,
    ordering_key,
)
from research.altcoin_multitf_inputs import UNIVERSE_SYMBOLS
from research.altcoin_multitf_phase3 import write_json_atomic
from research.altcoin_multitf_phase7 import DECIDE_END_EXCLUSIVE_MS, DECIDE_START_MS, sha256_file
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

PROTOCOL_ID = "ALTCOIN_CARRY_RM-001"
PROTOCOL_DOC = Path("docs/ALTCOIN_CARRY_RM_001_FROZEN_PROTOCOL.md")
ARTIFACTS = Path("reports/artifacts/altcoin-carry-rm-001")

SEED_SWEEP = 20260921
SEED_BOOTSTRAP = 20260922
SEED_SPA = 20260923

CORE_A = {"lookback_days": 3, "k_per_side": 3, "rebal_days": 1}
CORE_B = {"lookback_days": 7, "k_per_side": 2, "rebal_days": 1}
CORES = {"A": CORE_A, "B": CORE_B}
DD_STARTS = (0.05, 0.10)
DD_STOPS = (0.15, 0.20)
EXPECTED_GRID_COUNT = 8
HERITAGE_TRIALS = 6_044 + 8
TEMPORAL_MIN_POSITIVE_FOLDS = 7
NEIGHBOR_MIN_PROFITABLE_SHARE = 0.60

SPA_REPLICATES = 1000
BOOTSTRAP_REPLICATES = 2000
SHORTLIST_SIZE = 8

SWEEP_SCHEMA = "altcoin-carry-rm-001-sweep-v1"

PRIOR_INPUT_HASHES = {
    "primary_archive_sha256": "665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d",
    "supplement_archive_sha256": "a753585a11beb7bad74f9262920324fe8315a681b6dd108db072790bad47bd5b",
    "supplement_v2_archive_sha256": "487046fad5659e427075ca2b2b676bb3213da85276848129ba5eb21f00d10c56",
}


def config_key(core: str, dd_start: float, dd_stop: float) -> str:
    payload = json.dumps(
        {"core": core, "dd_start": dd_start, "dd_stop": dd_stop},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def frozen_grid() -> tuple[dict, ...]:
    grid = []
    seen = set()
    for core in ("A", "B"):
        for start in DD_STARTS:
            for stop in DD_STOPS:
                if not start < stop:
                    raise CarryError("overlay constraint violated: dd_start >= dd_stop")
                item = {"core": core, "dd_start": start, "dd_stop": stop}
                key = config_key(core, start, stop)
                if key in seen:
                    raise CarryError(f"configuration key collision: {key}")
                seen.add(key)
                grid.append(item)
    grid.sort(key=lambda c: config_key(c["core"], c["dd_start"], c["dd_stop"]))
    if len(grid) != EXPECTED_GRID_COUNT:
        raise CarryError(f"frozen RM-001 grid mismatch: {len(grid)} != {EXPECTED_GRID_COUNT}")
    return tuple(grid)


# ---------------------------------------------------------------------------


def exposure_multiplier(dd: float, dd_start: float, dd_stop: float) -> float:
    """Signed-dd map: dd <= 0; de-risk linearly between -dd_start and -dd_stop."""
    loss = -dd
    if loss <= dd_start:
        return 1.0
    return max(0.0, min(1.0, 1.0 - (loss - dd_start) / (dd_stop - dd_start)))


def simulate_rm(
    core_config: dict,
    dd_start: float,
    dd_stop: float,
    data: CarryData,
    trade_cost: float,
    *,
    stress_funding: str | None = None,
    use_overlay: bool = True,
) -> dict:
    """CARRY-001 recursion plus the frozen de-risking overlay.

    With ``use_overlay=False`` this reproduces the bare CARRY-001 simulator exactly
    (invariant covered by tests).
    """
    lookback, k, rebal = core_config["lookback_days"], core_config["k_per_side"], core_config["rebal_days"]
    weight = 1.0 / (2.0 * k)
    symbols = sorted(data.closes)

    days = [day for day in range(DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS, DAY_MS)]
    equity = 1.0
    peak = 1.0
    fractions = {s: 0.0 for s in symbols}
    daily_returns: list[float] = []
    episode_count = 0
    active: set[str] = set()
    symbol_pnl = {s: 0.0 for s in symbols}

    for index, day in enumerate(days):
        if not data.day_is_complete(day):
            daily_returns.append(0.0)
            continue
        price_term = 0.0
        funding_term = 0.0
        for symbol in symbols:
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
            return invalid_result(core_config, dd_start, dd_stop, "equity_non_positive")
        for symbol in symbols:
            rpx = data.price_return(symbol, day)
            fractions[symbol] = fractions[symbol] * (1.0 + rpx) / growth
        provisional_equity = equity * growth

        multiplier = 1.0
        if use_overlay:
            provisional_dd = provisional_equity / peak - 1.0
            multiplier = exposure_multiplier(provisional_dd, dd_start, dd_stop)

        cost_multiplier = 1.0
        if index % rebal == 0:
            signals = {s: data.signal(s, day, lookback) for s in symbols}
            if all(value is not None for value in signals.values()):
                ranked = sorted(symbols, key=lambda s: (-signals[s], s))
                shorts = set(ranked[:k])
                longs = set(ranked[len(ranked) - k:])
                turnover = 0.0
                for symbol in symbols:
                    target = (-weight if symbol in shorts else weight if symbol in longs else 0.0) * multiplier
                    turnover += abs(target - fractions[symbol])
                    fractions[symbol] = target
                cost_multiplier = max(0.0, 1.0 - trade_cost * turnover)
                episode_count += 2 * k
                active.update(shorts)
                active.update(longs)
        else:
            turnover = sum(abs((1.0 - multiplier) * fractions[s]) for s in symbols)
            if turnover > 0:
                for symbol in symbols:
                    fractions[symbol] *= multiplier
                cost_multiplier = max(0.0, 1.0 - trade_cost * turnover)

        previous_equity = equity
        equity = provisional_equity * cost_multiplier
        if equity > peak:
            peak = equity
        daily_returns.append(equity / previous_equity - 1.0)
    return {
        "config": {"core_config": dict(core_config), "dd_start": dd_start, "dd_stop": dd_stop},
        "key": _row_key(core_config, dd_start, dd_stop),
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


def _row_key(core_config: dict, dd_start: float, dd_stop: float) -> str:
    for name, cfg in CORES.items():
        if cfg == core_config:
            return config_key(name, dd_start, dd_stop)
    raise CarryError(f"core configuration outside frozen grid: {core_config}")


ITEMS_BY_KEY = {
    _row_key(CORES[item["core"]], item["dd_start"], item["dd_stop"]): item
    for item in frozen_grid()
}


def invalid_result(core_config: dict, dd_start: float, dd_stop: float, reason: str) -> dict:
    return {
        "config": {"core_config": dict(core_config), "dd_start": dd_start, "dd_stop": dd_stop},
        "key": _row_key(core_config, dd_start, dd_stop),
        "valid": False,
        "invalid_reason": reason,
        "net_equity": 1.0,
        "daily_returns": [],
        "episodes": 0,
        "active_assets": 0,
        "asset_names": [],
        "symbol_pnl": {},
        "final_fractions": {},
    }


def reference_run(core_config: dict, data: CarryData) -> dict:
    """Bare core without overlay — comparability anchor, excluded from gates."""
    return simulate_rm(core_config, 1.0, 2.0, data, PRIMARY_TRADE_COST, use_overlay=False)


def neighbor_keys(item: dict) -> list[dict]:
    variants = []
    for core in CORES:
        variants.append({**item, "core": core})
    for start in DD_STARTS:
        variants.append({**item, "dd_start": start})
    for stop in DD_STOPS:
        variants.append({**item, "dd_stop": stop})
    keys = {}
    for v in variants:
        keys.setdefault(_row_key(CORES[v["core"]], v["dd_start"], v["dd_stop"]), v)
    own = _row_key(CORES[item["core"]], item["dd_start"], item["dd_stop"])
    keys.pop(own, None)
    return [keys[k] for k in sorted(keys)]


def neighbor_profitability(item: dict, rows: dict[str, dict]) -> dict:
    evaluated = []
    for variant in neighbor_keys(item):
        key = _row_key(CORES[variant["core"]], variant["dd_start"], variant["dd_stop"])
        metrics = rows.get(key)
        if metrics is not None and metrics["valid"]:
            evaluated.append(metrics)
    profitable = sum(1 for m in evaluated if m["net_return"] > 0)
    denominator = len(evaluated)
    share = profitable / denominator if denominator else 0.0
    return {
        "neighbors_total": len(neighbor_keys(item)),
        "neighbors_evaluated_valid": denominator,
        "neighbors_profitable": profitable,
        "profitable_share": share,
        "gate_pass": denominator > 0 and share >= NEIGHBOR_MIN_PROFITABLE_SHARE,
    }


# ---------------------------------------------------------------------------
# sweep / finalize


def heritage_sharpe_variance_rm(extra_values: list[float]) -> dict:
    """Union of published Sharpes: 005+006+007+CARRY-001 plus current values."""
    values = list(extra_values)
    sources = [
        ("005", Path("reports/artifacts/altcoin-multitf-005-phase4/development-metrics.csv")),
        ("006", Path("reports/artifacts/altcoin-multitf-006/development-metrics.csv")),
        ("007", Path("reports/artifacts/altcoin-multitf-007/development-metrics.csv")),
        ("CARRY-001", Path("reports/artifacts/altcoin-carry-001/development-metrics.csv")),
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


def run_sweep(merged_root: Path, cache_dir: Path) -> dict:
    started = time.time()
    grid = frozen_grid()
    cache_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = cache_dir / "checkpoint-carry-rm-001.json"
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
            raise CarryError("resume rejected: RM-001 checkpoint identity mismatch")
        completed = payload.get("rows", {})
        references = payload.get("references", {})
    print(f"RM-001 sweep start: pending={len(grid)-len(completed)}", flush=True)
    if len(completed) < len(grid) or len(references) < len(CORES):
        data = CarryData.load(merged_root)
        pending = [c for c in grid if _row_key(CORES[c["core"]], c["dd_start"], c["dd_stop"]) not in completed]
        for index, item in enumerate(pending, 1):
            key = _row_key(CORES[item["core"]], item["dd_start"], item["dd_stop"])
            result = simulate_rm(CORES[item["core"]], item["dd_start"], item["dd_stop"], data, PRIMARY_TRADE_COST)
            completed[key] = config_metrics(key, item, result)
            print(f"RM-001 sweep {index}/{len(pending)} done elapsed={time.time()-started:.0f}s", flush=True)
        for core_name, core_cfg in CORES.items():
            ref_key = f"reference_{core_name}"
            if ref_key not in references:
                ref_result = reference_run(core_cfg, data)
                references[ref_key] = {
                    "net_return": ref_result["net_equity"] - 1.0,
                    "daily_sharpe": sharpe_ratio(ref_result["daily_returns"]),
                    "max_drawdown": max_drawdown_from_returns(ref_result["daily_returns"]),
                    "episodes": ref_result["episodes"],
                }
        write_json_atomic(checkpoint_path, {
            "schema": SWEEP_SCHEMA, "seed": SEED_SWEEP, "grid_count": EXPECTED_GRID_COUNT,
            "window": [DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS],
            "rows": completed, "references": references,
        })
    marker = {"expected": EXPECTED_GRID_COUNT, "completed": len(completed), "complete": len(completed) == EXPECTED_GRID_COUNT, "elapsed_seconds": time.time() - started}
    write_json_atomic(cache_dir / "completion-carry-rm-001.json", marker)
    if not marker["complete"]:
        raise CarryError("decide sweep incomplete")
    return marker


CSV_EXCLUDED = {"daily_returns", "fold_sharpes", "asset_names", "config"}


def finalize(cache_dir: Path) -> dict:
    started = time.time()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    payload = json.loads((cache_dir / "checkpoint-carry-rm-001.json").read_text(encoding="utf-8"))
    rows = payload["rows"]
    references = payload.get("references", {})
    if len(rows) != EXPECTED_GRID_COUNT:
        raise CarryError("unexpected decide row count")
    active_keys = sorted(k for k, r in rows.items() if r["valid"])
    write_json_atomic(ARTIFACTS / "sweep-progress.json", payload)
    sample = next(iter(rows.values()))
    header = sorted({**CORES[sample["config"]["core"]], **{k: v for k, v in sample.items() if k not in CSV_EXCLUDED}})
    with (ARTIFACTS / "development-metrics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for key in sorted(rows):
            row = rows[key]
            flat = {**CORES[row["config"]["core"]], "dd_start": row["config"]["dd_start"], "dd_stop": row["config"]["dd_stop"], **{k: v for k, v in row.items() if k not in CSV_EXCLUDED}}
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
    heritage = heritage_sharpe_variance_rm(sr_values)
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

    eligible = sorted((k for k in active_keys if is_eligible(rows[k])), key=lambda k: ordering_key(rows[k]))
    write_json_atomic(ARTIFACTS / "eligibility-table.json", {
        "eligible_count": len(eligible),
        "ordering": [{"rank": i + 1, "key": k} for i, k in enumerate(eligible[:SHORTLIST_SIZE])],
        "table": {
            k: {
                "episodes_ge_100": rows[k]["episodes"] >= 100,
                "positive_net_return": rows[k]["net_return"] > 0,
                "sharpe_above_0_5": rows[k]["annualized_sharpe"] is not None and rows[k]["annualized_sharpe"] > 0.5,
                "drawdown_within_limit": rows[k]["max_drawdown"] >= -0.25,
                "coverage_ge_6_assets": rows[k]["active_assets"] >= 6,
                "concentration_le_40pct": rows[k]["max_asset_positive_share"] <= 0.40,
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
        item = m["config"]
        ncheck = neighbor_profitability(item, rows)
        if not ncheck["gate_pass"]:
            failures.append("neighbors_share_below_60pct")
        if m["median_fold_sharpe"] <= 0 or m["positive_folds"] < TEMPORAL_MIN_POSITIVE_FOLDS:
            failures.append("temporal_consistency_failed")
        if failures:
            reports.append({"key": key, "failures": failures})
            continue
        if data is None:
            merged_root = Path(r"D:\alt-multitf-005-data\inputs") / "merged"
            data = CarryData.load(merged_root)
        boot = circular_block_bootstrap_mean_ci(m["daily_returns"], replicates=BOOTSTRAP_REPLICATES, seed=SEED_BOOTSTRAP)
        stress = {}
        for name, cost in STRESS_TRADE_COSTS.items():
            net = simulate_rm(CORES[item["core"]], item["dd_start"], item["dd_stop"], data, cost)["net_equity"] - 1.0
            stress[name] = {"net_return": net, "pass": net > 0}
        for name, mode in (("funding_half", "half"), ("funding_flipped", "flipped")):
            net = simulate_rm(CORES[item["core"]], item["dd_start"], item["dd_stop"], data, PRIMARY_TRADE_COST, stress_funding=mode)["net_equity"] - 1.0
            stress[name] = {"net_return": net, "pass": net > 0}
        maker_net = simulate_rm(CORES[item["core"]], item["dd_start"], item["dd_stop"], data, MAKER_TRADE_COST)["net_equity"] - 1.0
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
        verdict["consequence"] = "risk-managed carry unproven as deployable"
    write_json_atomic(ARTIFACTS / "verdict-final.json", verdict)
    repo_commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    manifest = {
        "protocol_id": PROTOCOL_ID,
        "repo_source_commit": repo_commit,
        "frozen_protocol_document": PROTOCOL_DOC.name,
        "frozen_protocol_sha256": sha256_file(PROTOCOL_DOC),
        "freeze_proof_commit": "68482d4",
        "erratum_commit": "9209620",
        "prior_inputs": PRIOR_INPUT_HASHES,
        "windows_utc": {
            "decide": ["2021-01-01T00:00:00Z", "2026-07-01T00:00:00Z"],
            "monitor_reserve": ["2026-07-01T00:00:00Z", None],
        },
        "universe_used": list(UNIVERSE_SYMBOLS),
        "selection_policy": "single-pass decision; hypothesis-level NO_SELECTION only; reference rows excluded from gates",
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
    parser.add_argument("--cache-dir", type=Path, default=Path(r"D:\alt-multitf-005-data\carry-rm-001-cache"))
    parser.add_argument("--stage", choices=("sweep", "finalize", "all"), required=False)
    args = parser.parse_args(argv)
    if args.validate_grid:
        grid = frozen_grid()
        print(json.dumps({"count": len(grid), "first_key": config_key(grid[0]["core"], grid[0]["dd_start"], grid[0]["dd_stop"]), "seed": SEED_SWEEP}, sort_keys=True))
        return 0
    merged_root = args.inputs_root / "merged"
    if args.stage in ("sweep", "all"):
        print(json.dumps(run_sweep(merged_root, args.cache_dir), sort_keys=True))
    if args.stage in ("finalize", "all"):
        print(json.dumps(finalize(args.cache_dir), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
