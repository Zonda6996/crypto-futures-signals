"""ALTCOIN_CARRY_SL_001 deterministic sweep runner (carry with stops & takes).

Implements the frozen protocol `docs/ALTCOIN_CARRY_SL_001_FROZEN_PROTOCOL.md`.
The CARRY-001 family is upgraded to EPISODE-based holding: a position keeps its
identity (side, entry price, risk distance) across days while it stays ranked, and
leaves early on rank-drop, funding-flip, price stop (Wilder ATR-scaled or fixed
benchmark), or a mechanical take-profit (partial/full, optional breakeven trail for
the remainder). Freed slots refill immediately from the live ranking; a symbol
manually exited today cannot re-open the same close. Daily trim to target weight
remains the built-in partial profit-taking; an anti-blowup cap trims any fraction
beyond twice its target.

Grid: Block 1 compares stop styles (take = none); Block 2 compares take rules
(stop = atr3). Bare-core and fixed-stop references sit outside the gates. The monitor
reserve (2026-07..) is never read by this module.
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
    simulate as carry_simulate,
)
from research.altcoin_multitf_inputs import UNIVERSE_SYMBOLS
from research.altcoin_multitf_phase3 import write_json_atomic
from research.altcoin_multitf_phase7 import DECIDE_END_EXCLUSIVE_MS, DECIDE_START_MS, FOLD_BOUNDS_007, sha256_file
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

PROTOCOL_ID = "ALTCOIN_CARRY_SL-001"
PROTOCOL_DOC = Path("docs/ALTCOIN_CARRY_SL_001_FROZEN_PROTOCOL.md")
ARTIFACTS = Path("reports/artifacts/altcoin-carry-sl-001")
SUPPLEMENT_ROOT = "altcoin-multitf-006-supplement"

SEED_SWEEP = 20260928
SEED_BOOTSTRAP = 20260929
SEED_SPA = 20260930

CORE_A = {"lookback_days": 3, "k_per_side": 3, "rebal_days": 1}
CORE_B = {"lookback_days": 7, "k_per_side": 2, "rebal_days": 1}
CORES = {"A": CORE_A, "B": CORE_B}

STOP_STYLES_BLOCK1 = ("atr2", "atr3", "flip", "atr2flip")
BLOCK2_STOP = "atr3"
TAKE_CODES_BLOCK2 = (
    "p1:1+BU", "p1:1", "f1:1",
    "p1:1.5+BU", "p1:1.5", "f1:1.5",
    "p1:2+BU", "p1:2", "f1:2",
    "p1:3+BU", "f1:3",
)
EXPECTED_GRID_COUNT = 30

ATR_PERIOD = 14
FIXED_STOP_FRACTION = 0.10
BLOWUP_CAP_MULTIPLE = 2.0

HERITAGE_TRIALS = 6_052 + EXPECTED_GRID_COUNT  # 6,082
TEMPORAL_MIN_POSITIVE_FOLDS = 7
NEIGHBOR_MIN_PROFITABLE_SHARE = 0.60

SPA_REPLICATES = 1000
BOOTSTRAP_REPLICATES = 2000

SWEEP_SCHEMA = "altcoin-carry-sl-001-sweep-v1"

PRIOR_INPUT_HASHES = {
    "primary_archive_sha256": "665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d",
    "supplement_archive_sha256": "a753585a11beb7bad74f9262920324fe8315a681b6dd108db072790bad47bd5b",
    "supplement_v2_archive_sha256": "487046fad5659e427075ca2b2b676bb3213da85276848129ba5eb21f00d10c56",
}


class SlError(RuntimeError):
    pass


def item_key(core_name: str, stop_style: str, take_code: str) -> str:
    payload = json.dumps(
        {"core": CORES[core_name], "stop_style": stop_style, "take_code": take_code},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def frozen_grid() -> tuple[dict, ...]:
    items = []
    seen = set()
    spec = []
    for stop_style in STOP_STYLES_BLOCK1:
        spec.append((stop_style, "none"))
    for take_code in TAKE_CODES_BLOCK2:
        spec.append((BLOCK2_STOP, take_code))
    for core_name in ("A", "B"):
        for stop_style, take_code in spec:
            key = item_key(core_name, stop_style, take_code)
            if key in seen:
                continue  # atr3+none appears in both block specs
            seen.add(key)
            items.append({
                "core_name": core_name,
                "core": CORES[core_name],
                "stop_style": stop_style,
                "take_code": take_code,
                "key": key,
                "block": 1 if take_code == "none" else 2,
            })
    items.sort(key=lambda i: i["key"])
    unique = {(i["core_name"], i["stop_style"], i["take_code"]) for i in items}
    if len(items) != EXPECTED_GRID_COUNT or len(unique) != EXPECTED_GRID_COUNT:
        raise SlError(f"frozen SL-001 grid mismatch: {len(items)} != {EXPECTED_GRID_COUNT}")
    return tuple(items)


ITEMS_BY_KEY = {i["key"]: i for i in frozen_grid()}


# ---------------------------------------------------------------------------
# data


def _read_daily_ohlc(path: Path, end_exclusive_ms: int) -> dict[str, dict[int, float]]:
    if not path.is_file():
        raise SlError(f"missing normalized series: {path}")
    series: dict[str, dict[int, float]] = {"high": {}, "low": {}, "close": {}}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            open_ms = int(row["open_time_ms"])
            if open_ms >= end_exclusive_ms:
                continue
            series["high"][open_ms] = float(row["high"])
            series["low"][open_ms] = float(row["low"])
            series["close"][open_ms] = float(row["close"])
    if not series["close"]:
        raise SlError(f"empty series: {path}")
    return series


def wilder_atr(highs: dict[int, float], lows: dict[int, float], closes: dict[int, float], period: int) -> dict[int, float]:
    days = sorted(closes)
    atr_by_day: dict[int, float] = {}
    previous_close = None
    true_ranges: list[float] = []
    smoothed = None
    for index, day in enumerate(days):
        if previous_close is None:
            previous_close = closes[day]
            continue
        h, l = highs[day], lows[day]
        tr = max(h - l, abs(h - previous_close), abs(l - previous_close))
        previous_close = closes[day]
        if smoothed is None:
            true_ranges.append(tr)
            if len(true_ranges) == period:
                smoothed = sum(true_ranges) / period
                atr_by_day[day] = smoothed
            continue
        smoothed = ((period - 1) * smoothed + tr) / period
        atr_by_day[day] = smoothed
    return atr_by_day


class SlData(CarryData):
    """CarryData plus daily highs/lows and per-symbol Wilder ATR(14)."""

    def __init__(self, carry: CarryData, atr: dict[str, dict[int, float]]) -> None:
        super().__init__(carry.closes, carry.funding_by_day, carry.funding_counts_by_day, carry.funding_first_ts)
        self.atr = atr

    @classmethod
    def load(cls, merged_root: Path) -> "SlData":
        base = merged_root.resolve() / SUPPLEMENT_ROOT / "development" / "normalized"
        end = DECIDE_END_EXCLUSIVE_MS
        carry = CarryData.load(merged_root)
        atr = {}
        for symbol in UNIVERSE_SYMBOLS:
            ohlc = _read_daily_ohlc(base / "klines" / symbol / f"{symbol}-1d.csv.gz", end)
            atr[symbol] = wilder_atr(ohlc["high"], ohlc["low"], ohlc["close"], ATR_PERIOD)
        return cls(carry, atr)


# ---------------------------------------------------------------------------
# take-rule parsing


def take_params(take_code: str) -> tuple[float, str, bool] | None:
    """Returns (R, mode, breakeven) or None for 'none'.

    Codes: none | p<R-part>+BU | p<R-part> | f<R-part>, where <R-part> looks like
    ``1:1``, ``1.5:1.5`` etc.; the ratio is the segment after the colon.
    """
    if take_code == "none":
        return None
    partial = take_code.startswith("p")
    body = take_code[1:]
    breakeven = body.endswith("+BU")
    if breakeven:
        body = body[:-3]
    ratio = float(body.rsplit(":", 1)[1])
    return ratio, ("partial" if partial else "full"), breakeven


def stop_has_price(stop_style: str) -> bool:
    return stop_style in ("atr2", "atr3", "atr2flip", "fixed10")


def stop_multiplier(stop_style: str) -> float | None:
    if stop_style in ("atr2", "atr2flip"):
        return 2.0
    if stop_style == "atr3":
        return 3.0
    return None


def stop_has_flip(stop_style: str) -> bool:
    return stop_style in ("flip", "atr2flip")


# ---------------------------------------------------------------------------
# episode simulation


def simulate_sl(item: dict, data: SlData, trade_cost: float, *, stress_funding: str | None = None) -> dict:
    core = item["core"]
    stop_style = item["stop_style"]
    take_code = item["take_code"]
    lookback, k, rebal = core["lookback_days"], core["k_per_side"], core["rebal_days"]
    weight = 1.0 / (2.0 * k)
    take = take_params(take_code)
    symbols = sorted(data.closes)

    fractions = {s: 0.0 for s in symbols}
    episodes: dict[str, dict] = {}
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
            return invalid_result(item, "equity_non_positive")
        for symbol in symbols:
            rpx = data.price_return(symbol, day)
            fractions[symbol] = fractions[symbol] * (1.0 + rpx) / growth
        provisional_equity = equity * growth

        rebalance_day = index % rebal == 0
        signals = {s: data.signal(s, day, lookback) for s in symbols}
        signals_valid = all(v is not None for v in signals.values())
        shorts = longs = None
        if rebalance_day and signals_valid:
            ranked = sorted(symbols, key=lambda s: (-signals[s], s))
            shorts = set(ranked[:k])
            longs = set(ranked[len(ranked) - k:])

        turnover = 0.0
        exited_today: set[str] = set()

        # --- exits (frozen order: rank-drop, flip, stop, take) ---
        for symbol in sorted(episodes):
            episode = episodes[symbol]
            side = episode["side"]
            price = data.closes[symbol][day]
            reason = None
            action_full_exit = False
            partial_sell = 0.0
            if shorts is not None:
                if side < 0 and symbol not in shorts:
                    reason = "rank_drop"
                elif side > 0 and symbol not in longs:
                    reason = "rank_drop"
            if reason is None and stop_has_flip(stop_style) and signals[symbol] is not None:
                if (side > 0 and signals[symbol] >= 0) or (side < 0 and signals[symbol] <= 0):
                    reason = "flip"
            if reason is None and stop_has_price(stop_style):
                if stop_style == "fixed10":
                    dist_effective = FIXED_STOP_FRACTION * episode["entry"]
                elif episode["be"]:
                    dist_effective = 0.0
                else:
                    dist_effective = episode["dist"]
                if side > 0 and price <= episode["entry"] - dist_effective:
                    reason = "stop"
                elif side < 0 and price >= episode["entry"] + dist_effective:
                    reason = "stop"
            if reason is None and take is not None and not episode["taken"]:
                ratio, mode, breakeven = take
                favorable = (price - episode["entry"]) if side > 0 else (episode["entry"] - price)
                if favorable >= ratio * episode["dist"]:
                    reason = "take"
                    if mode == "full":
                        action_full_exit = True
                    else:
                        partial_sell = abs(fractions[symbol]) / 2.0
            if reason is None:
                continue
            if action_full_exit:
                turnover += abs(fractions[symbol])
                fractions[symbol] = 0.0
                del episodes[symbol]
                exited_today.add(symbol)
            elif partial_sell > 0:
                turnover += partial_sell
                fractions[symbol] -= partial_sell * (1 if fractions[symbol] > 0 else -1)
                episode["taken"] = True
                if take[2]:  # breakeven remainder
                    episode["be"] = True
            else:
                turnover += abs(fractions[symbol])
                fractions[symbol] = 0.0
                del episodes[symbol]
                if reason != "rank_drop":
                    exited_today.add(symbol)

        # --- refills on re-ranking closes ---
        if shorts is not None:
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
                    if stop_style in ("atr2", "atr2flip"):
                        dist = 2.0 * data.atr[symbol][day]
                    elif stop_style == "atr3":
                        dist = 3.0 * data.atr[symbol][day]
                    elif stop_style == "fixed10":
                        dist = FIXED_STOP_FRACTION * entry_price
                    else:  # flip-only: distance defined solely for take accounting
                        dist = data.atr[symbol][day]
                    episodes[symbol] = {"side": side, "entry": entry_price, "dist": dist, "be": False, "taken": False}
                    holders.append(symbol)
                    episode_count += 1
                    active.add(symbol)

        # --- targets: held episodes to ±weight, others flat (daily trim) ---
        for symbol in symbols:
            target = 0.0
            if symbol in episodes:
                target = weight if episodes[symbol]["side"] > 0 else -weight
            turnover += abs(target - fractions[symbol])
            fractions[symbol] = target

        # --- anti-blowup cap (post-trim guard; binds only if trim skipped) ---
        for symbol in symbols:
            if abs(fractions[symbol]) > BLOWUP_CAP_MULTIPLE * weight:
                excess_target = BLOWUP_CAP_MULTIPLE * weight * (1 if fractions[symbol] > 0 else -1)
                turnover += abs(excess_target - fractions[symbol])
                fractions[symbol] = excess_target

        previous_equity = equity
        equity = provisional_equity * max(0.0, 1.0 - trade_cost * turnover)
        daily_returns.append(equity / previous_equity - 1.0)

    return {
        "config": {"core_name": item["core_name"], "stop_style": stop_style, "take_code": take_code},
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
    }


def invalid_result(item: dict, reason: str) -> dict:
    return {
        "config": {"core_name": item["core_name"], "stop_style": item["stop_style"], "take_code": item["take_code"]},
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
    }


# ---------------------------------------------------------------------------
# neighbours


def neighbor_items(item: dict) -> list[dict]:
    variants = []
    for core_name in CORES:
        variants.append({**item, "core_name": core_name, "core": CORES[core_name]})
    for stop_style in (*STOP_STYLES_BLOCK1, BLOCK2_STOP):
        variants.append({**item, "stop_style": stop_style})
    for take_code in ("none", *TAKE_CODES_BLOCK2):
        variants.append({**item, "take_code": take_code})
    keys = {}
    for v in variants:
        key = item_key(v["core_name"], v["stop_style"], v["take_code"])
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


def heritage_sharpe_variance_sl(extra_values: list[float]) -> dict:
    values = list(extra_values)
    sources = [
        ("005", Path("reports/artifacts/altcoin-multitf-005-phase4/development-metrics.csv")),
        ("006", Path("reports/artifacts/altcoin-multitf-006/development-metrics.csv")),
        ("007", Path("reports/artifacts/altcoin-multitf-007/development-metrics.csv")),
        ("CARRY-001", Path("reports/artifacts/altcoin-carry-001/development-metrics.csv")),
        ("RM-001", Path("reports/artifacts/altcoin-carry-rm-001/development-metrics.csv")),
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
    core = CORES[row["config"]["core_name"]]
    return {
        "lookback_days": core["lookback_days"],
        "k_per_side": core["k_per_side"],
        "rebal_days": core["rebal_days"],
        "stop_style": row["config"]["stop_style"],
        "take_code": row["config"]["take_code"],
        **{k: v for k, v in row.items() if k not in CSV_EXCLUDED},
    }


def run_sweep(merged_root: Path, cache_dir: Path) -> dict:
    started = time.time()
    grid = frozen_grid()
    cache_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = cache_dir / "checkpoint-carry-sl-001.json"
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
            raise SlError("resume rejected: SL-001 checkpoint identity mismatch")
        completed = payload.get("rows", {})
        references = payload.get("references", {})
    print(f"SL-001 sweep start: pending={len(grid)-len(completed)}", flush=True)
    if len(completed) < len(grid) or len(references) < 4:
        data = SlData.load(merged_root)
        pending = [i for i in grid if i["key"] not in completed]
        for index, item in enumerate(pending, 1):
            result = simulate_sl(item, data, PRIMARY_TRADE_COST)
            completed[item["key"]] = config_metrics(item["key"], result["config"], result)
            write_json_atomic(checkpoint_path, {
                "schema": SWEEP_SCHEMA, "seed": SEED_SWEEP, "grid_count": EXPECTED_GRID_COUNT,
                "window": [DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS],
                "rows": completed, "references": references,
            })
            print(f"SL-001 sweep {index}/{len(pending)} done elapsed={time.time()-started:.0f}s", flush=True)
        for core_name in ("A", "B"):
            ref_bare = f"reference_bare_{core_name}"
            ref_fixed = f"reference_fixed10_{core_name}"
            if ref_bare not in references:
                bare = carry_simulate(CORES[core_name], data, PRIMARY_TRADE_COST)
                references[ref_bare] = {
                    "net_return": bare["net_equity"] - 1.0,
                    "daily_sharpe": sharpe_ratio(bare["daily_returns"]),
                    "max_drawdown": max_drawdown_from_returns(bare["daily_returns"]),
                    "episodes": bare["episodes"],
                }
            if ref_fixed not in references:
                item = {"core_name": core_name, "core": CORES[core_name], "stop_style": "fixed10",
                        "take_code": "none", "key": f"ref-{core_name}-fixed10"}
                fixed = simulate_sl(item, data, PRIMARY_TRADE_COST)
                references[ref_fixed] = {
                    "net_return": fixed["net_equity"] - 1.0,
                    "daily_sharpe": sharpe_ratio(fixed["daily_returns"]),
                    "max_drawdown": max_drawdown_from_returns(fixed["daily_returns"]),
                    "episodes": fixed["episodes"],
                }
        write_json_atomic(checkpoint_path, {
            "schema": SWEEP_SCHEMA, "seed": SEED_SWEEP, "grid_count": EXPECTED_GRID_COUNT,
            "window": [DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS],
            "rows": completed, "references": references,
        })
    marker = {"expected": EXPECTED_GRID_COUNT, "completed": len(completed), "complete": len(completed) == EXPECTED_GRID_COUNT, "elapsed_seconds": time.time() - started}
    write_json_atomic(cache_dir / "completion-carry-sl-001.json", marker)
    if not marker["complete"]:
        raise SlError("decide sweep incomplete")
    return marker


def finalize(cache_dir: Path) -> dict:
    started = time.time()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    payload = json.loads((cache_dir / "checkpoint-carry-sl-001.json").read_text(encoding="utf-8"))
    rows = payload["rows"]
    references = payload.get("references", {})
    if len(rows) != EXPECTED_GRID_COUNT:
        raise SlError("unexpected decide row count")
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
    heritage = heritage_sharpe_variance_sl(sr_values)
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
            reports.append({"key": key, "block": ITEMS_BY_KEY[key]["block"], "failures": failures})
            continue
        if data is None:
            merged_root = Path(r"D:\alt-multitf-005-data\inputs") / "merged"
            data = SlData.load(merged_root)
        boot = circular_block_bootstrap_mean_ci(m["daily_returns"], replicates=BOOTSTRAP_REPLICATES, seed=SEED_BOOTSTRAP)
        stress = {}
        for name, cost in STRESS_TRADE_COSTS.items():
            net = simulate_sl(ITEMS_BY_KEY[key], data, cost)["net_equity"] - 1.0
            stress[name] = {"net_return": net, "pass": net > 0}
        for name, mode in (("funding_half", "half"), ("funding_flipped", "flipped")):
            net = simulate_sl(ITEMS_BY_KEY[key], data, PRIMARY_TRADE_COST, stress_funding=mode)["net_equity"] - 1.0
            stress[name] = {"net_return": net, "pass": net > 0}
        maker_net = simulate_sl(ITEMS_BY_KEY[key], data, MAKER_TRADE_COST)["net_equity"] - 1.0
        if boot["lower"] <= 0:
            failures.append("bootstrap_ci_lower_not_positive")
        failures.extend(f"stress_{n}_failed" for n, o in sorted(stress.items()) if not o["pass"])
        reports.append({
            "key": key, "block": ITEMS_BY_KEY[key]["block"], "bootstrap": boot, "stress": stress,
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
        verdict["consequence"] = "carry with stops/takes unproven as deployable"
    write_json_atomic(ARTIFACTS / "verdict-final.json", verdict)
    repo_commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    manifest = {
        "protocol_id": PROTOCOL_ID,
        "repo_source_commit": repo_commit,
        "frozen_protocol_document": PROTOCOL_DOC.name,
        "frozen_protocol_sha256": sha256_file(PROTOCOL_DOC),
        "freeze_proof_commit": "afb3794",
        "prior_inputs": PRIOR_INPUT_HASHES,
        "windows_utc": {
            "decide": ["2021-01-01T00:00:00Z", "2026-07-01T00:00:00Z"],
            "monitor_reserve": ["2026-07-01T00:00:00Z", None],
        },
        "universe_used": list(UNIVERSE_SYMBOLS),
        "selection_policy": "single-pass decision on the complete grid; block-1 review is reporting only",
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
    parser.add_argument("--cache-dir", type=Path, default=Path(r"D:\alt-multitf-005-data\carry-sl-001-cache"))
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
