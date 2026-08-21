from __future__ import annotations

import csv
import json
import random
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from .core import Bar, CostModel, ExitRules, Trade, simulate_trade, utc_iso
from .data import INTERVAL_MS, download_symbol
from .features import make_features
from .phase1_audit import CANDIDATE
from .regime_concentration import causal_btc_regimes, summarize_values
from .search import calibrate_candidate, evaluate_candidate
from .timeframe_robustness import seal_before_test

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "reports" / "phase5"
YEARS = (2021, 2024)
TEST_START_TS = 1_735_689_600_000
DAY_MS = 86_400_000
BASE_COST = CostModel(5, 0, 0)
STRESS_COST = CostModel(8, 0, 0)
ADVERSE_SIDE_RETURN = 0.0003
MISSED_SEEDS = {5: 5005, 10: 1010, 20: 2020}


def total(rows: list[dict]) -> float:
    return sum(float(row["result_r"]) for row in rows)


def period_key(ts: int, months: int) -> str:
    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    start_month = ((dt.month - 1) // months) * months + 1
    return f"{dt.year}-{start_month:02d}"


def calendar_blocks(rows: list[dict], months: int) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(period_key(int(row["signal_ts"]), months), []).append(row)
    return [{"period": key, "months": months, **summarize_values([float(r["result_r"]) for r in group])}
            for key, group in sorted(groups.items())]


def rolling_windows(rows: list[dict], months: int) -> list[dict]:
    if not rows:
        return []
    first = datetime.fromtimestamp(int(rows[0]["signal_ts"]) / 1000, tz=timezone.utc)
    last_ts = int(rows[-1]["signal_ts"])
    year, month = first.year, first.month
    output = []
    while True:
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        end_month = month - 1 + months
        end = datetime(year + end_month // 12, end_month % 12 + 1, 1, tzinfo=timezone.utc)
        start_ts, end_ts = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
        if end_ts > TEST_START_TS or start_ts > last_ts:
            break
        selected = [row for row in rows if start_ts <= int(row["signal_ts"]) < end_ts]
        output.append({"start": start.isoformat(), "end": end.isoformat(), "months": months,
                       **summarize_values([float(row["result_r"]) for row in selected])})
        month = month % 12 + 1
        if month == 1:
            year += 1
    return output


def remove_best_periods(rows: list[dict], months: int, counts: tuple[int, ...]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(period_key(int(row["signal_ts"]), months), []).append(row)
    ranked = sorted(groups, key=lambda key: total(groups[key]), reverse=True)
    return [{"unit": "week" if months == 0 else "month", "removed_count": count,
             "removed_periods": ranked[:count], "remaining_total_r": total(
                 [row for key, group in groups.items() if key not in ranked[:count] for row in group])}
            for count in counts]


def week_key(ts: int) -> str:
    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def remove_best_weeks(rows: list[dict], counts: tuple[int, ...] = (1, 3, 5)) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(week_key(int(row["signal_ts"])), []).append(row)
    ranked = sorted(groups, key=lambda key: total(groups[key]), reverse=True)
    return [{"unit": "week", "removed_count": count, "removed_periods": ranked[:count],
             "remaining_total_r": total([row for key, group in groups.items()
                                          if key not in ranked[:count] for row in group])}
            for count in counts]


def best_continuous_cluster(rows: list[dict], days: int) -> dict:
    best_total, best_start, best_end = float("-inf"), None, None
    for row in rows:
        start = int(row["signal_ts"])
        end = start + days * DAY_MS
        value = total([item for item in rows if start <= int(item["signal_ts"]) < end])
        if value > best_total:
            best_total, best_start, best_end = value, start, end
    return {"days": days, "cluster_total_r": best_total, "start": utc_iso(best_start),
            "end": utc_iso(best_end), "remaining_total_r": total(rows) - best_total}


def path_diagnostics(rows: list[dict]) -> dict:
    equity = peak = 0.0
    peak_ts = int(rows[0]["signal_ts"]) if rows else None
    longest_underwater = max_losing = losing = 0
    recovery_days = []
    for row in rows:
        equity += float(row["result_r"])
        ts = int(row["signal_ts"])
        if float(row["result_r"]) < 0:
            losing += 1
            max_losing = max(max_losing, losing)
        else:
            losing = 0
        if equity >= peak:
            if peak_ts is not None:
                recovery_days.append((ts - peak_ts) / DAY_MS)
            peak, peak_ts = equity, ts
        elif peak_ts is not None:
            longest_underwater = max(longest_underwater, int((ts - peak_ts) / DAY_MS))
    return {"maximum_losing_streak": max_losing, "longest_no_new_high_days": longest_underwater,
            "maximum_recovery_days": max(recovery_days, default=0)}


def deterministic_keep(rows: list[dict], missed_percent: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    return [row for row in rows if rng.random() >= missed_percent / 100]


def verdict(criteria: dict[str, bool]) -> dict:
    return {"pass": all(criteria.values()), "criteria": criteria,
            "failed": [name for name, passed in criteria.items() if not passed]}

def rows_from_trades(trades: list[Trade], bars: list[Bar], features: list[dict], regimes: list[dict]) -> list[dict]:
    index = {bar.ts: i for i, bar in enumerate(bars)}
    rows = []
    for trade in trades:
        i = index[trade.signal_ts]
        risk = CANDIDATE.stop_atr * float(features[i]["atr_24"]) / trade.entry
        regime = regimes[i]["regime"]
        rows.append({"signal_ts": trade.signal_ts, "signal_time": utc_iso(trade.signal_ts),
                     "entry_time": utc_iso(trade.entry_ts), "exit_time": utc_iso(trade.exit_ts),
                     "calendar_year": datetime.fromtimestamp(trade.signal_ts / 1000, tz=timezone.utc).year,
                     "quarter": period_key(trade.signal_ts, 3), "half_year": period_key(trade.signal_ts, 6),
                     "regime": regime, "exit_reason": trade.exit_reason, "gross_return": trade.gross_return,
                     "funding_return": trade.funding_return, "cost_return": trade.cost_return,
                     "net_return": trade.net_return, "initial_risk_return": risk,
                     "result_r": trade.net_return / risk})
    return rows


def stressed_rows(base_trades: list[Trade], bars: list[Bar], features: list[dict], regimes: list[dict],
                  costs: CostModel, execution_delay: int = 1, adverse_each_side: float = 0.0,
                  funding_multiplier: float = 1.0, missed_percent: int = 0, seed: int = 0) -> tuple[list[dict], dict]:
    index = {bar.ts: i for i, bar in enumerate(bars)}
    selected = base_trades
    if missed_percent:
        rng = random.Random(seed)
        selected = [trade for trade in base_trades if rng.random() >= missed_percent / 100]
    stressed = []
    dropped = 0
    rules = ExitRules(CANDIDATE.horizon, CANDIDATE.stop_atr, CANDIDATE.take_atr)
    for base in selected:
        i = index[base.signal_ts]
        trade = simulate_trade(bars, i, base.side, float(features[i]["atr_24"]), rules, costs, {}, execution_delay)
        if trade is None:
            dropped += 1
            continue
        gross = trade.gross_return - 2 * adverse_each_side
        funding = base.funding_return * funding_multiplier
        net = gross + funding - trade.cost_return
        stressed.append(replace(trade, gross_return=gross, funding_return=funding, net_return=net))
    return rows_from_trades(stressed, bars, features, regimes), {
        "source_trades": len(base_trades), "kept_trades": len(stressed), "dropped": dropped,
        "cost_model": asdict(costs), "execution_delay_bars": execution_delay,
        "adverse_each_side": adverse_each_side, "funding_multiplier": funding_multiplier,
        "missed_percent": missed_percent, "seed": seed if missed_percent else None,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def analyze() -> dict:
    btc_raw, _, btc_manifest = download_symbol("BTCUSDT", *YEARS, DATA, interval="1h")
    eth_raw, funding_raw, eth_manifest = download_symbol("ETHUSDT", *YEARS, DATA, interval="1h")
    btc, eth = seal_before_test(btc_raw), seal_before_test(eth_raw)
    funding = [(ts, value) for ts, value in funding_raw if ts < TEST_START_TS]
    if not eth or eth[-1].ts + INTERVAL_MS["1h"] != TEST_START_TS:
        raise RuntimeError("pre-TEST data must end exactly at 2025-01-01")
    if [bar.ts for bar in btc] != [bar.ts for bar in eth]:
        raise RuntimeError("BTC and ETH timelines must align")
    if any(bar.ts >= TEST_START_TS for bar in btc + eth) or any(ts >= TEST_START_TS for ts, _ in funding):
        raise RuntimeError("sealed TEST data entered Phase 5")

    features = make_features(eth, funding, btc)
    train_stop = int(len(eth) * 0.75)
    calibration = calibrate_candidate(CANDIDATE, features, list(range(train_stop)))
    base_trades, _ = evaluate_candidate(CANDIDATE, eth, features, list(range(len(eth))), BASE_COST,
                                        dict(funding), calibration)
    regimes = causal_btc_regimes(btc, 1)
    rows = rows_from_trades(base_trades, eth, features, regimes)
    if any(int(row["signal_ts"]) >= TEST_START_TS for row in rows):
        raise RuntimeError("sealed TEST trade entered Phase 5")

    calendar = calendar_blocks(rows, 3) + calendar_blocks(rows, 6)
    rolling = [item for months in (6, 12, 18) for item in rolling_windows(rows, months)]
    clusters = [best_continuous_cluster(rows, days) for days in (30, 60, 90)]
    removals = remove_best_weeks(rows) + remove_best_periods(rows, 1, (1, 3))
    years = {str(year): summarize_values([float(row["result_r"]) for row in rows
                                          if row["calendar_year"] == year])
             for year in sorted({row["calendar_year"] for row in rows})}
    best_year = max(years, key=lambda year: years[year]["total_r"])
    without_best_year = total([row for row in rows if str(row["calendar_year"]) != best_year])
    regime_labels = sorted({row["regime"] for row in rows if row["regime"] != "insufficient_history"})
    leave_regime = {label: summarize_values([float(row["result_r"]) for row in rows
                                             if row["regime"] != label]) for label in regime_labels}

    scenario_specs = {
        "cost_0_16pct": dict(costs=STRESS_COST),
        "entry_delay_1_extra_bar": dict(costs=BASE_COST, execution_delay=2),
        "missed_5pct": dict(costs=BASE_COST, missed_percent=5, seed=MISSED_SEEDS[5]),
        "missed_10pct": dict(costs=BASE_COST, missed_percent=10, seed=MISSED_SEEDS[10]),
        "missed_20pct": dict(costs=BASE_COST, missed_percent=20, seed=MISSED_SEEDS[20]),
        "adverse_slippage": dict(costs=BASE_COST, adverse_each_side=ADVERSE_SIDE_RETURN),
        "funding_x2": dict(costs=BASE_COST, funding_multiplier=2.0),
        "combined": dict(costs=STRESS_COST, adverse_each_side=ADVERSE_SIDE_RETURN,
                         funding_multiplier=2.0, missed_percent=10, seed=MISSED_SEEDS[10]),
    }
    scenarios = {}
    scenario_csv = []
    for name, spec in scenario_specs.items():
        stressed, metadata = stressed_rows(base_trades, eth, features, regimes, **spec)
        summary = summarize_values([float(row["result_r"]) for row in stressed])
        scenarios[name] = {**metadata, **summary}
        scenario_csv.append({"scenario": name, **metadata, **summary})

    baseline = summarize_values([float(row["result_r"]) for row in rows])
    rolling_12 = [item for item in rolling if item["months"] == 12]
    positive_12_share = sum(item["total_r"] > 0 for item in rolling_12) / len(rolling_12)
    criteria = {
        "positive_without_top_5": baseline["without_top_5_r"] > 0,
        "positive_without_best_year": without_best_year > 0,
        "positive_without_best_90d_cluster": clusters[2]["remaining_total_r"] > 0,
        "positive_at_0_16pct_cost": scenarios["cost_0_16pct"]["total_r"] > 0,
        "rolling_12m_positive_share_over_50pct": positive_12_share > 0.5,
        "all_leave_one_causal_regime_out_positive": all(item["total_r"] > 0 for item in leave_regime.values()),
        "combined_execution_stress_non_negative": scenarios["combined"]["total_r"] >= 0,
    }
    result = {
        "study": "Phase 5 frozen 1h final pre-TEST falsification", "test_opened": False,
        "separate_from_phases_2_to_4": True, "protocol": "docs/PHASE5_PROTOCOL.md",
        "sample": {"years": list(YEARS), "train_indices": [0, train_stop],
                   "evaluated_train_validation_indices": [0, len(eth)], "last_included_ts": eth[-1].ts,
                   "sealed_test_start_ts": TEST_START_TS},
        "candidate": asdict(CANDIDATE), "calibration": asdict(calibration), "baseline": baseline,
        "calendar_years": years, "best_year": best_year, "without_best_year_r": without_best_year,
        "rolling_12m_positive_share": positive_12_share, "path": path_diagnostics(rows),
        "clusters": clusters, "period_removals": removals, "leave_one_regime_out": leave_regime,
        "execution_scenarios": scenarios, "verdict": verdict(criteria),
        "integrity": {"trade_rows": len(rows), "calendar_rows": len(calendar), "rolling_rows": len(rolling),
                      "scenario_rows": len(scenario_csv), "all_timestamps_before_test": True,
                      "btc_quality": btc_manifest["quality"], "eth_quality": eth_manifest["quality"]},
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUTPUT / "trades.csv", rows)
    write_csv(OUTPUT / "calendar-blocks.csv", calendar)
    write_csv(OUTPUT / "rolling-windows.csv", rolling)
    write_csv(OUTPUT / "execution-scenarios.csv", scenario_csv)
    (OUTPUT / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def markdown(result: dict) -> str:
    status = "PASS" if result["verdict"]["pass"] else "FAIL"
    lines = ["# Phase 5 — frozen 1h final pre-TEST falsification", "", f"Verdict: **{status}**.", "",
             "TEST с `2025-01-01` не загружался, не анализировался и не открывался.", "",
             "## Criteria", "", "| Criterion | Result |", "|---|---:|"]
    for name, passed in result["verdict"]["criteria"].items():
        lines.append(f"| `{name}` | {'PASS' if passed else 'FAIL'} |")
    b = result["baseline"]
    lines += ["", "## Baseline", "", f"- Trades: {b['trades']}", f"- Total: `{b['total_r']:+.3f}R`",
              f"- Without top-5: `{b['without_top_5_r']:+.3f}R`",
              f"- Without best year ({result['best_year']}): `{result['without_best_year_r']:+.3f}R`",
              f"- Rolling 12m positive share: `{100 * result['rolling_12m_positive_share']:.1f}%`", "",
              "## Continuous clusters", ""]
    for item in result["clusters"]:
        lines.append(f"- Without best {item['days']}d cluster: `{item['remaining_total_r']:+.3f}R`.")
    lines += ["", "## Execution", ""]
    for name, item in result["execution_scenarios"].items():
        lines.append(f"- `{name}`: {item['trades']} trades, `{item['total_r']:+.3f}R`.")
    lines += ["", "## Interpretation", "",
              "Phase 5 is a descriptive full pre-TEST falsification, not a new OOS estimate. No failed scenario may be discarded, regimes are not trading filters, and the verdict cannot be changed after observing results.", ""]
    return "\n".join(lines)


def run() -> dict:
    result = analyze()
    (ROOT / "reports" / "PHASE5_FALSIFICATION.md").write_text(markdown(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run()["verdict"], indent=2))
