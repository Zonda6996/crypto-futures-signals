"""ALTCOIN_XS_001 deterministic sweep runner (cross-sectional momentum).

Implements the frozen protocol `docs/ALTCOIN_XS_001_FROZEN_PROTOCOL.md`: the ten
universe perps are ranked by trailing `window_days` price return at each rebalance
close; the engine goes LONG the top-K / SHORT the bottom-K with dollar-neutral
targets ±1/(2K), drifts between rebalances, accrues funding daily and pays
proportional costs on turnover. Simulation contract, metrics and the full gate
stack are reused unchanged from the CARRY-001 engine.

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

PROTOCOL_ID = "ALTCOIN_XS-001"
PROTOCOL_DOC = Path("docs/ALTCOIN_XS_001_FROZEN_PROTOCOL.md")
ARTIFACTS = Path("reports/artifacts/altcoin-xs-001")
SUPPLEMENT_ROOT = "altcoin-multitf-006-supplement"

SEED_SWEEP = 20261019
SEED_BOOTSTRAP = 20261020
SEED_SPA = 20261021

WINDOWS = (3, 7, 14)
K_PER_SIDE = (2, 3)
REBAL_DAYS = (1, 7)
EXPECTED_GRID_COUNT = 12
HERITAGE_TRIALS = 6_122 + EXPECTED_GRID_COUNT  # 6,134
TEMPORAL_MIN_POSITIVE_FOLDS = 7
NEIGHBOR_MIN_PROFITABLE_SHARE = 0.60

SPA_REPLICATES = 1000
BOOTSTRAP_REPLICATES = 2000
SHORTLIST_SIZE = 12

SWEEP_SCHEMA = "altcoin-xs-001-sweep-v1"

PRIOR_INPUT_HASHES = {
    "primary_archive_sha256": "665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d",
    "supplement_archive_sha256": "a753585a11beb7bad74f9262920324fe8315a681b6dd108db072790bad47bd5b",
    "supplement_v2_archive_sha256": "487046fad5659e427075ca2b2b676bb3213da85276848129ba5eb21f00d10c56",
}


class XsError(RuntimeError):
    pass


def config_key(config: dict) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def frozen_grid() -> tuple[dict, ...]:
    grid = []
    seen = set()
    for window in WINDOWS:
        for k in K_PER_SIDE:
            for rebal in REBAL_DAYS:
                config = {"window_days": window, "k_per_side": k, "rebal_days": rebal}
                key = config_key(config)
                if key in seen:
                    raise XsError(f"key collision: {key}")
                seen.add(key)
                grid.append(config)
    grid.sort(key=config_key)
    if len(grid) != EXPECTED_GRID_COUNT:
        raise XsError(f"grid mismatch: {len(grid)} != {EXPECTED_GRID_COUNT}")
    return tuple(grid)


def simulate_xs(config: dict, data: CarryData, trade_cost: float, *, stress_funding: str | None = None) -> dict:
    window, k, rebal = config["window_days"], config["k_per_side"], config["rebal_days"]
    weight = 1.0 / (2.0 * k)
    symbols = sorted(data.closes)

    fractions = {s: 0.0 for s in symbols}
    equity = 1.0
    daily_returns: list[float] = []
    episode_count = 0
    active: set[str] = set()
    symbol_pnl = {s: 0.0 for s in symbols}

    days = [day for day in range(DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS, DAY_MS)]
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
            return invalid_result(config, "equity_non_positive")
        for symbol in symbols:
            rpx = data.price_return(symbol, day)
            fractions[symbol] = fractions[symbol] * (1.0 + rpx) / growth
        cost_multiplier = 1.0
        if index % rebal == 0:
            momenta = {}
            for symbol in symbols:
                closes = data.closes[symbol]
                start = day - window * DAY_MS
                if start not in closes or day not in closes:
                    momenta[symbol] = None
                    continue
                momenta[symbol] = closes[day] / closes[start] - 1.0
            if all(v is not None for v in momenta.values()):
                ranked = sorted(symbols, key=lambda s: (-momenta[s], s))
                longs = set(ranked[:k])
                shorts = set(ranked[len(ranked) - k:])
                turnover = 0.0
                for symbol in symbols:
                    target = weight if symbol in longs else -weight if symbol in shorts else 0.0
                    turnover += abs(target - fractions[symbol])
                    fractions[symbol] = target
                cost_multiplier = max(0.0, 1.0 - trade_cost * turnover)
                episode_count += 2 * k
                active.update(longs)
                active.update(shorts)
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
        "config": dict(config), "key": config_key(config), "valid": False,
        "invalid_reason": reason, "net_equity": 1.0, "daily_returns": [],
        "episodes": 0, "active_assets": 0, "asset_names": [], "symbol_pnl": {},
        "final_fractions": {},
    }


def neighbor_keys(config: dict) -> list[str]:
    variants = []
    for window in WINDOWS:
        variants.append({**config, "window_days": window})
    for k in K_PER_SIDE:
        variants.append({**config, "k_per_side": k})
    for rebal in REBAL_DAYS:
        variants.append({**config, "rebal_days": rebal})
    keys = {config_key(v) for v in variants}
    keys.discard(config_key(config))
    return sorted(k for k in keys if k in {config_key(c) for c in frozen_grid()})


def neighbor_profitability(config: dict, rows: dict[str, dict]) -> dict:
    keys = neighbor_keys(config)
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


def heritage_sharpe_variance_xs(extra_values: list[float]) -> dict:
    values = list(extra_values)
    sources = [
        ("005", Path("reports/artifacts/altcoin-multitf-005-phase4/development-metrics.csv")),
        ("006", Path("reports/artifacts/altcoin-multitf-006/development-metrics.csv")),
        ("007", Path("reports/artifacts/altcoin-multitf-007/development-metrics.csv")),
        ("CARRY-001", Path("reports/artifacts/altcoin-carry-001/development-metrics.csv")),
        ("RM-001", Path("reports/artifacts/altcoin-carry-rm-001/development-metrics.csv")),
        ("SL-001", Path("reports/artifacts/altcoin-carry-sl-001/development-metrics.csv")),
        ("FINAL-001", Path("reports/artifacts/altcoin-carry-final-001/development-metrics.csv")),
        ("MR-TF-001", Path("reports/artifacts/altcoin-mr-tf-001/development-metrics.csv")),
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

# ---------------------------------------------------------------------------
# sweep / finalize


CSV_EXCLUDED = {"daily_returns", "fold_sharpes", "fold_net_returns", "asset_names", "config"}


def _flat_row(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in CSV_EXCLUDED}


def _references(data: CarryData) -> dict:
    out = {}
    for name, symbol in (("reference_bh_basket", None), ("reference_bh_btc", "BTCUSDT")):
        rets = []
        picks = UNIVERSE_SYMBOLS if symbol is None else [symbol]
        d1 = data.closes[picks[0]]
        days = [d for d in sorted(d1) if DECIDE_START_MS <= d < DECIDE_END_EXCLUSIVE_MS]
        prev = None
        for day in days:
            if prev is not None:
                if symbol is not None:
                    rets.append(d1[day] / d1[prev] - 1.0)
                else:
                    leg = 0.0
                    for s in picks:
                        cs = data.closes[s]
                        leg += cs[day] / cs[prev] - 1.0
                    rets.append(leg / len(picks))
            prev = day
        equity = 1.0
        for r in rets:
            equity *= 1.0 + r
        out[name] = {"net_return": equity - 1.0, "daily_sharpe": sharpe_ratio(rets),
                     "max_drawdown": max_drawdown_from_returns(rets)}
    return out


def run_sweep(merged_root: Path, cache_dir: Path) -> dict:
    started = time.time()
    grid = frozen_grid()
    cache_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = cache_dir / "checkpoint-xs-001.json"
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
            raise XsError("resume rejected: XS-001 checkpoint identity mismatch")
        completed = payload.get("rows", {})
        references = payload.get("references", {})
    print(f"XS-001 sweep start: pending={len(grid)-len(completed)}", flush=True)
    if len(completed) < len(grid) or len(references) < 2:
        data = CarryData.load(merged_root)
        pending = [c for c in grid if config_key(c) not in completed]
        for index, config in enumerate(pending, 1):
            result = simulate_xs(config, data, PRIMARY_TRADE_COST)
            completed[config_key(config)] = config_metrics(config_key(config), config, result)
            write_json_atomic(checkpoint_path, {
                "schema": SWEEP_SCHEMA, "seed": SEED_SWEEP, "grid_count": EXPECTED_GRID_COUNT,
                "window": [DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS],
                "rows": completed, "references": references,
            })
            print(f"XS-001 sweep {index}/{len(pending)} done elapsed={time.time()-started:.0f}s", flush=True)
        references = _references(data)
        write_json_atomic(checkpoint_path, {
            "schema": SWEEP_SCHEMA, "seed": SEED_SWEEP, "grid_count": EXPECTED_GRID_COUNT,
            "window": [DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS],
            "rows": completed, "references": references,
        })
    marker = {"expected": EXPECTED_GRID_COUNT, "completed": len(completed), "complete": len(completed) == EXPECTED_GRID_COUNT, "elapsed_seconds": time.time() - started}
    write_json_atomic(cache_dir / "completion-xs-001.json", marker)
    if not marker["complete"]:
        raise XsError("decide sweep incomplete")
    return marker


def finalize(cache_dir: Path, merged_root: Path) -> dict:
    started = time.time()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    payload = json.loads((cache_dir / "checkpoint-xs-001.json").read_text(encoding="utf-8"))
    rows = payload["rows"]
    references = payload.get("references", {})
    if len(rows) != EXPECTED_GRID_COUNT:
        raise XsError("unexpected decide row count")
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
    heritage = heritage_sharpe_variance_xs(sr_values)
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
        "table": {k: {
            "episodes_ge_100": rows[k]["episodes"] >= 100,
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
            net = simulate_xs(m["config"], data, cost)["net_equity"] - 1.0
            stress[name] = {"net_return": net, "pass": net > 0}
        for name, mode in (("funding_half", "half"), ("funding_flipped", "flipped")):
            net = simulate_xs(m["config"], data, PRIMARY_TRADE_COST, stress_funding=mode)["net_equity"] - 1.0
            stress[name] = {"net_return": net, "pass": net > 0}
        maker_net = simulate_xs(m["config"], data, MAKER_TRADE_COST)["net_equity"] - 1.0
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
        verdict["consequence"] = "cross-sectional momentum unproven on this universe"
    write_json_atomic(ARTIFACTS / "verdict-final.json", verdict)
    repo_commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    manifest = {
        "protocol_id": PROTOCOL_ID,
        "repo_source_commit": repo_commit,
        "frozen_protocol_document": PROTOCOL_DOC.name,
        "frozen_protocol_sha256": sha256_file(PROTOCOL_DOC),
        "freeze_proof_commit": "8635b73",
        "prior_inputs": PRIOR_INPUT_HASHES,
        "downloads": "none",
        "windows_utc": {
            "decide": ["2021-01-01T00:00:00Z", "2026-07-01T00:00:00Z"],
            "monitor_reserve": ["2026-07-01T00:00:00Z", None],
        },
        "universe_used": list(UNIVERSE_SYMBOLS),
        "selection_policy": "single-pass decision; XS family closes on NO_SELECTION",
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
    parser.add_argument("--cache-dir", type=Path, default=Path(r"D:\alt-multitf-005-data\xs-001-cache"))
    parser.add_argument("--stage", choices=("sweep", "finalize", "all"), required=False)
    args = parser.parse_args(argv)
    if args.validate_grid:
        grid = frozen_grid()
        print(json.dumps({"count": len(grid), "first_key": config_key(grid[0]), "seed": SEED_SWEEP}, sort_keys=True))
        return 0
    merged_root = args.inputs_root / "merged"
    if args.stage in ("sweep", "all"):
        print(json.dumps(run_sweep(merged_root, args.cache_dir), sort_keys=True))
    if args.stage in ("finalize", "all"):
        print(json.dumps(finalize(args.cache_dir, merged_root), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
