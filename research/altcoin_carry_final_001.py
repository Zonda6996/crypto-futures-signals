"""ALTCOIN_CARRY_FINAL_001 deterministic sweep runner (hardened carry).

Implements the frozen protocol `docs/ALTCOIN_CARRY_FINAL_001_FROZEN_PROTOCOL.md`:
the SL-001 champion (core A + atr3 stop + full take 1:1) as a fixed base arm with
three orthogonal hardening axes — market-beta hedge (BTC-perp leg sized by trailing
90d betas), inverse-volatility position weights (30d sigma, gross preserved), and a
funding-dispersion deployment gate (open while current cross-sectional signal
dispersion is at/above its trailing 180-day median; closed gate blocks new episodes
only). The all-off grid corner must reproduce the published SL-001 champion exactly
(hard invariant, unit-tested).

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
    CarryError,
    DAY_MS,
    MAKER_TRADE_COST,
    PRIMARY_TRADE_COST,
    STRESS_TRADE_COSTS,
    config_metrics,
    is_eligible,
    max_drawdown_from_returns,
    ordering_key,
    simulate as carry_simulate,
)
from research.altcoin_carry_sl_001 import (
    CORES,
    ITEMS_BY_KEY as SL_ITEMS_BY_KEY,
    SlData,
    simulate_sl,
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

PROTOCOL_ID = "ALTCOIN_CARRY_FINAL-001"
PROTOCOL_DOC = Path("docs/ALTCOIN_CARRY_FINAL_001_FROZEN_PROTOCOL.md")
ARTIFACTS = Path("reports/artifacts/altcoin-carry-final-001")

SEED_SWEEP = 20261005
SEED_BOOTSTRAP = 20261006
SEED_SPA = 20261007

EXPECTED_GRID_COUNT = 8
HERITAGE_TRIALS = 6_082 + EXPECTED_GRID_COUNT  # 6,090
TEMPORAL_MIN_POSITIVE_FOLDS = 7
NEIGHBOR_MIN_PROFITABLE_SHARE = 0.60

HEDGE_VALUES = (False, True)
WEIGHT_VALUES = ("equal", "invvol")
GATE_VALUES = ("always", "dispersion")

BETA_WINDOW = 90
SIGMA_WINDOW = 30
DISPERSION_MEDIAN_WINDOW_DAYS = 180

BASE_CORE = CORES["A"]
BASE_STOP_STYLE = "atr3"
BASE_TAKE_CODE = "f1:1"

SPA_REPLICATES = 1000
BOOTSTRAP_REPLICATES = 2000

SWEEP_SCHEMA = "altcoin-carry-final-001-sweep-v1"

PRIOR_INPUT_HASHES = {
    "primary_archive_sha256": "665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d",
    "supplement_archive_sha256": "a753585a11beb7bad74f9262920324fe8315a681b6dd108db072790bad47bd5b",
    "supplement_v2_archive_sha256": "487046fad5659e427075ca2b2b676bb3213da85276848129ba5eb21f00d10c56",
}


class FinalError(RuntimeError):
    pass


def item_key(hedge: bool, weights: str, gate: str) -> str:
    payload = json.dumps(
        {"base": "A/atr3/f1:1", "hedge": hedge, "weights": weights, "gate": gate},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def frozen_grid() -> tuple[dict, ...]:
    items = []
    seen = set()
    for hedge in HEDGE_VALUES:
        for weights in WEIGHT_VALUES:
            for gate in GATE_VALUES:
                key = item_key(hedge, weights, gate)
                if key in seen:
                    raise FinalError(f"configuration key collision: {key}")
                seen.add(key)
                items.append({
                    "key": key,
                    "hedge": hedge,
                    "weights": weights,
                    "gate": gate,
                    "core_name": "A",
                    "core": BASE_CORE,
                    "stop_style": BASE_STOP_STYLE,
                    "take_code": BASE_TAKE_CODE,
                })
    items.sort(key=lambda i: i["key"])
    if len(items) != EXPECTED_GRID_COUNT:
        raise FinalError(f"frozen FINAL-001 grid mismatch: {len(items)} != {EXPECTED_GRID_COUNT}")
    return tuple(items)


ITEMS_BY_KEY = {i["key"]: i for i in frozen_grid()}


# ---------------------------------------------------------------------------
# causal statistics helpers


def _returns_series(data: SlData, symbol: str, day: int, count: int) -> list[float] | None:
    """Daily returns for `count` days ENDING at the previous close (causal)."""
    out = []
    for offset in range(count, 0, -1):
        d = day - offset * DAY_MS
        d_prev = d - DAY_MS
        if d not in data.closes[symbol] or d_prev not in data.closes[symbol]:
            return None
        out.append(data.closes[symbol][d] / data.closes[symbol][d_prev] - 1.0)
    return out


def trailing_sigma(data: SlData, symbol: str, day: int) -> float | None:
    series = _returns_series(data, symbol, day, SIGMA_WINDOW)
    if series is None:
        return None
    mean = sum(series) / len(series)
    return (sum((v - mean) ** 2 for v in series) / len(series)) ** 0.5


def trailing_beta(data: SlData, symbol: str, day: int) -> float:
    """beta of symbol vs BTC over BETA_WINDOW returns ending at previous close."""
    rs = _returns_series(data, symbol, day, BETA_WINDOW)
    rb = _returns_series(data, "BTCUSDT", day, BETA_WINDOW)
    if rs is None or rb is None:
        return 1.0
    mean_s = sum(rs) / len(rs)
    mean_b = sum(rb) / len(rb)
    cov = sum((a - mean_s) * (b - mean_b) for a, b in zip(rs, rb)) / len(rs)
    var = sum((b - mean_b) ** 2 for b in rb) / len(rb)
    if var <= 0:
        return 1.0
    return cov / var


def dispersion_series(data: SlData) -> dict[int, float]:
    """Cross-sectional std of the ten funding signals per day."""
    lookback = BASE_CORE["lookback_days"]
    out: dict[int, float] = {}
    for day in range(DECIDE_START_MS - 400 * DAY_MS, DECIDE_END_EXCLUSIVE_MS, DAY_MS):
        signals = [data.signal(s, day, lookback) for s in UNIVERSE_SYMBOLS]
        if any(v is None for v in signals):
            continue
        mean = sum(signals) / len(signals)
        out[day] = (sum((v - mean) ** 2 for v in signals) / len(signals)) ** 0.5
    return out


def gate_is_open(disp_by_day: dict[int, float], day: int) -> bool:
    """OPEN when current dispersion >= median of the trailing 180-day window
    ending at the previous close. Falls back to OPEN while history is short."""
    window = []
    d = day - DAY_MS
    while d in disp_by_day and len(window) < DISPERSION_MEDIAN_WINDOW_DAYS:
        window.append(disp_by_day[d])
        d -= DAY_MS
    if len(window) < DISPERSION_MEDIAN_WINDOW_DAYS:
        return True
    current = disp_by_day.get(day)
    if current is None:
        return True
    ordered = sorted(window)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return current >= median


# ---------------------------------------------------------------------------
# simulation


def simulate_final(item: dict, data: SlData, trade_cost: float, *, stress_funding: str | None = None) -> dict:
    lookback, k, rebal = BASE_CORE["lookback_days"], BASE_CORE["k_per_side"], BASE_CORE["rebal_days"]
    weight = 1.0 / (2.0 * k)
    symbols = sorted(data.closes)
    disp_by_day = dispersion_series(data) if item["gate"] == "dispersion" else None

    fractions = {s: 0.0 for s in symbols}
    episodes: dict[str, dict] = {}
    hedge_frac = 0.0
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

        def _f(symbol: str, w: float) -> float:
            f = data.funding_sum(symbol, day)
            if stress_funding == "half":
                f *= 0.5
            elif stress_funding == "flipped":
                f = -f
            return f

        price_term = 0.0
        funding_term = 0.0
        total_frac = {s: fractions[s] for s in symbols}
        if item["hedge"]:
            total_frac["BTCUSDT"] = fractions["BTCUSDT"] + hedge_frac
        for symbol in symbols:
            rpx = data.price_return(symbol, day)
            f = _f(symbol, total_frac[symbol])
            w = total_frac[symbol]
            price_term += w * rpx
            funding_term -= w * f
            symbol_pnl[symbol] += w * rpx - w * f
        growth = 1.0 + price_term + funding_term
        if not growth > 0:
            return invalid_result(item, "equity_non_positive")
        for symbol in symbols:
            rpx = data.price_return(symbol, day)
            fractions[symbol] = fractions[symbol] * (1.0 + rpx) / growth
        hedge_frac = hedge_frac / growth
        provisional_equity = equity * growth

        rebalance_day = index % rebal == 0
        signals = {s: data.signal(s, day, lookback) for s in symbols}
        signals_valid = all(v is not None for v in signals.values())
        shorts = longs = None
        if rebalance_day and signals_valid:
            ranked = sorted(symbols, key=lambda s: (-signals[s], s))
            shorts = set(ranked[:k])
            longs = set(ranked[len(ranked) - k:])

        gate_open = True
        if item["gate"] == "dispersion":
            gate_open = gate_is_open(disp_by_day, day)

        turnover = 0.0
        exited_today: set[str] = set()

        # --- exits (frozen order: rank-drop, stop, take; flip inactive for atr3) ---
        for symbol in sorted(episodes):
            episode = episodes[symbol]
            side = episode["side"]
            price = data.closes[symbol][day]
            reason = None
            action_full_exit = False
            if shorts is not None:
                if side < 0 and symbol not in shorts:
                    reason = "rank_drop"
                elif side > 0 and symbol not in longs:
                    reason = "rank_drop"
            if reason is None:
                dist_effective = 0.0 if episode["be"] else episode["dist"]
                if side > 0 and price <= episode["entry"] - dist_effective:
                    reason = "stop"
                elif side < 0 and price >= episode["entry"] + dist_effective:
                    reason = "stop"
            if reason is None:
                ratio, mode, breakeven = (1.0, "full", False)
                favorable = (price - episode["entry"]) if side > 0 else (episode["entry"] - price)
                if favorable >= ratio * episode["dist"]:
                    reason = "take"
                    action_full_exit = True
            if reason is None:
                continue
            turnover += abs(fractions[symbol])
            fractions[symbol] = 0.0
            del episodes[symbol]
            if reason != "rank_drop" and not action_full_exit:
                exited_today.add(symbol)
            elif reason == "take":
                exited_today.add(symbol)

        # --- refills (blocked while gate CLOSED) ---
        if shorts is not None and gate_open:
            for side, ranked_side in ((-1, sorted(shorts)), (+1, sorted(longs))):
                holders = [s for s, e in episodes.items() if e["side"] == side]
                for symbol in ranked_side:
                    if len(holders) >= k:
                        break
                    if symbol in holders or symbol in exited_today or symbol in episodes:
                        continue
                    if data.atr.get(symbol, {}).get(day) is None:
                        continue
                    entry_price = data.closes[symbol][day]
                    dist = 3.0 * data.atr[symbol][day]
                    episodes[symbol] = {"side": side, "entry": entry_price, "dist": dist, "be": False, "taken": False}
                    holders.append(symbol)
                    episode_count += 1
                    active.add(symbol)

        # --- targets: equal or inverse-vol, gross preserved ---
        held = list(episodes)
        if item["weights"] == "invvol" and held:
            invols = {}
            for symbol in held:
                sigma = trailing_sigma(data, symbol, day)
                invols[symbol] = (1.0 / sigma) if sigma and sigma > 0 else None
            known = [s for s in held if invols[s] is not None]
            denom = sum(invols[s] for s in known)
            for symbol in symbols:
                target = 0.0
                if symbol in episodes:
                    side = episodes[symbol]["side"]
                    if symbol in known and denom > 0:
                        target = side * invols[symbol] / denom
                    else:
                        target = side * weight
                turnover += abs(target - fractions[symbol])
                fractions[symbol] = target
        else:
            for symbol in symbols:
                target = 0.0
                if symbol in episodes:
                    target = weight if episodes[symbol]["side"] > 0 else -weight
                turnover += abs(target - fractions[symbol])
                fractions[symbol] = target

        # --- hedge leg ---
        if item["hedge"]:
            beta_book = sum(fractions[s] * trailing_beta(data, s, day) for s in symbols)
            new_hedge = -beta_book
            turnover += abs(new_hedge - hedge_frac)
            hedge_frac = new_hedge

        previous_equity = equity
        equity = provisional_equity * max(0.0, 1.0 - trade_cost * turnover)
        daily_returns.append(equity / previous_equity - 1.0)

    return {
        "config": {
            "core_name": "A", "stop_style": BASE_STOP_STYLE, "take_code": BASE_TAKE_CODE,
            "hedge": item["hedge"], "weights": item["weights"], "gate": item["gate"],
        },
        "key": item["key"],
        "valid": True,
        "invalid_reason": None,
        "net_equity": equity,
        "daily_returns": daily_returns,
        "episodes": episode_count,
        "active_assets": len(active),
        "asset_names": sorted(active),
        "symbol_pnl": symbol_pnl,
        "final_fractions": dict(fractions),
        "final_hedge": hedge_frac,
    }


def invalid_result(item: dict, reason: str) -> dict:
    return {
        "config": {
            "core_name": "A", "stop_style": BASE_STOP_STYLE, "take_code": BASE_TAKE_CODE,
            "hedge": item["hedge"], "weights": item["weights"], "gate": item["gate"],
        },
        "key": item["key"],
        "valid": False,
        "invalid_reason": reason,
        "net_equity": 1.0,
        "daily_returns": [],
        "episodes": 0,
        "active_assets": 0,
        "asset_names": [],
        "symbol_pnl": {},
        "final_fractions": {},
        "final_hedge": 0.0,
    }


def neighbor_items(item: dict) -> list[dict]:
    variants = []
    for hedge in HEDGE_VALUES:
        variants.append({**item, "hedge": hedge})
    for weights in WEIGHT_VALUES:
        variants.append({**item, "weights": weights})
    for gate in GATE_VALUES:
        variants.append({**item, "gate": gate})
    keys = {}
    for v in variants:
        key = item_key(v["hedge"], v["weights"], v["gate"])
        if key in ITEMS_BY_KEY:
            keys.setdefault(key, ITEMS_BY_KEY[key])
    keys.pop(item["key"], None)
    return [keys[k] for k in sorted(keys)]


def neighbor_profitability(item: dict, rows: dict[str, dict]) -> dict:
    evaluated = []
    for variant in neighbor_items(item):
        metrics = rows.get(variant["key"])
        if metrics is not None and metrics["valid"]:
            evaluated.append(metrics)
    profitable = sum(1 for m in evaluated if m["net_return"] > 0)
    denominator = len(evaluated)
    share = profitable / denominator if denominator else 0.0
    return {
        "neighbors_total": len(neighbor_items(item)),
        "neighbors_evaluated_valid": denominator,
        "neighbors_profitable": profitable,
        "profitable_share": share,
        "gate_pass": denominator > 0 and share >= NEIGHBOR_MIN_PROFITABLE_SHARE,
    }


# ---------------------------------------------------------------------------
# heritage


def heritage_sharpe_variance_final(extra_values: list[float]) -> dict:
    values = list(extra_values)
    sources = [
        ("005", Path("reports/artifacts/altcoin-multitf-005-phase4/development-metrics.csv")),
        ("006", Path("reports/artifacts/altcoin-multitf-006/development-metrics.csv")),
        ("007", Path("reports/artifacts/altcoin-multitf-007/development-metrics.csv")),
        ("CARRY-001", Path("reports/artifacts/altcoin-carry-001/development-metrics.csv")),
        ("RM-001", Path("reports/artifacts/altcoin-carry-rm-001/development-metrics.csv")),
        ("SL-001", Path("reports/artifacts/altcoin-carry-sl-001/development-metrics.csv")),
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


CSV_EXCLUDED = {"daily_returns", "fold_sharpes", "asset_names", "config"}


def _flat_row(row: dict) -> dict:
    return {
        "lookback_days": BASE_CORE["lookback_days"],
        "k_per_side": BASE_CORE["k_per_side"],
        "rebal_days": BASE_CORE["rebal_days"],
        "stop_style": BASE_STOP_STYLE,
        "take_code": BASE_TAKE_CODE,
        "hedge": row["config"]["hedge"],
        "weights": row["config"]["weights"],
        "gate": row["config"]["gate"],
        **{k: v for k, v in row.items() if k not in CSV_EXCLUDED},
    }


def run_sweep(merged_root: Path, cache_dir: Path) -> dict:
    started = time.time()
    grid = frozen_grid()
    cache_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = cache_dir / "checkpoint-carry-final-001.json"
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
            raise FinalError("resume rejected: FINAL-001 checkpoint identity mismatch")
        completed = payload.get("rows", {})
        references = payload.get("references", {})
    print(f"FINAL-001 sweep start: pending={len(grid)-len(completed)}", flush=True)
    if len(completed) < len(grid) or len(references) < 3:
        data = SlData.load(merged_root)
        pending = [i for i in grid if i["key"] not in completed]
        for index, item in enumerate(pending, 1):
            result = simulate_final(item, data, PRIMARY_TRADE_COST)
            completed[item["key"]] = config_metrics(item["key"], result["config"], result)
            write_json_atomic(checkpoint_path, {
                "schema": SWEEP_SCHEMA, "seed": SEED_SWEEP, "grid_count": EXPECTED_GRID_COUNT,
                "window": [DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS],
                "rows": completed, "references": references,
            })
            print(f"FINAL-001 sweep {index}/{len(pending)} done elapsed={time.time()-started:.0f}s", flush=True)
        risk_item = {"core_name": "A", "core": BASE_CORE, "stop_style": "atr3", "take_code": "p1:2+BU", "key": "ref-risk"}
        ref_defs = {
            "reference_risk_arm": lambda: simulate_sl(risk_item, data, PRIMARY_TRADE_COST),
            "reference_bare_A": lambda: carry_simulate(CORES["A"], data, PRIMARY_TRADE_COST),
            "reference_bare_B": lambda: carry_simulate(CORES["B"], data, PRIMARY_TRADE_COST),
        }
        for name, fn in ref_defs.items():
            if name in references:
                continue
            result = fn()
            references[name] = {
                "net_return": result["net_equity"] - 1.0,
                "daily_sharpe": sharpe_ratio(result["daily_returns"]),
                "max_drawdown": max_drawdown_from_returns(result["daily_returns"]),
                "episodes": result["episodes"],
            }
        write_json_atomic(checkpoint_path, {
            "schema": SWEEP_SCHEMA, "seed": SEED_SWEEP, "grid_count": EXPECTED_GRID_COUNT,
            "window": [DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS],
            "rows": completed, "references": references,
        })
    marker = {"expected": EXPECTED_GRID_COUNT, "completed": len(completed), "complete": len(completed) == EXPECTED_GRID_COUNT, "elapsed_seconds": time.time() - started}
    write_json_atomic(cache_dir / "completion-carry-final-001.json", marker)
    if not marker["complete"]:
        raise FinalError("decide sweep incomplete")
    return marker


def finalize(cache_dir: Path) -> dict:
    started = time.time()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    payload = json.loads((cache_dir / "checkpoint-carry-final-001.json").read_text(encoding="utf-8"))
    rows = payload["rows"]
    references = payload.get("references", {})
    if len(rows) != EXPECTED_GRID_COUNT:
        raise FinalError("unexpected decide row count")
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
    heritage = heritage_sharpe_variance_final(sr_values)
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
        "ordering": [{"rank": i + 1, "key": k} for i, k in enumerate(eligible)],
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
            data = SlData.load(merged_root)
        boot = circular_block_bootstrap_mean_ci(m["daily_returns"], replicates=BOOTSTRAP_REPLICATES, seed=SEED_BOOTSTRAP)
        stress = {}
        for name, cost in STRESS_TRADE_COSTS.items():
            net = simulate_final(ITEMS_BY_KEY[key], data, cost)["net_equity"] - 1.0
            stress[name] = {"net_return": net, "pass": net > 0}
        for name, mode in (("funding_half", "half"), ("funding_flipped", "flipped")):
            net = simulate_final(ITEMS_BY_KEY[key], data, PRIMARY_TRADE_COST, stress_funding=mode)["net_equity"] - 1.0
            stress[name] = {"net_return": net, "pass": net > 0}
        maker_net = simulate_final(ITEMS_BY_KEY[key], data, MAKER_TRADE_COST)["net_equity"] - 1.0
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
        verdict["consequence"] = "hardened carry unproven; carry family in-sample work concluded"
    write_json_atomic(ARTIFACTS / "verdict-final.json", verdict)
    repo_commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    manifest = {
        "protocol_id": PROTOCOL_ID,
        "repo_source_commit": repo_commit,
        "frozen_protocol_document": PROTOCOL_DOC.name,
        "frozen_protocol_sha256": sha256_file(PROTOCOL_DOC),
        "freeze_proof_commit": "240598a",
        "prior_inputs": PRIOR_INPUT_HASHES,
        "downloads": "none (all inputs local); no exchangeInfo snapshot required by this protocol",
        "windows_utc": {
            "decide": ["2021-01-01T00:00:00Z", "2026-07-01T00:00:00Z"],
            "monitor_reserve": ["2026-07-01T00:00:00Z", None],
        },
        "universe_used": list(UNIVERSE_SYMBOLS),
        "selection_policy": "single-pass decision; last planned in-sample pass over the carry family",
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
    parser.add_argument("--cache-dir", type=Path, default=Path(r"D:\alt-multitf-005-data\carry-final-001-cache"))
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
