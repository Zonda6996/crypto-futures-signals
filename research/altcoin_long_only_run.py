"""Single DEVELOPMENT/TRAIN run for frozen ALT-LOMOM-002-A."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .altcoin_basket_data import BASKET, HOLDOUT_START_ISO, HOLDOUT_START_MS, utc_iso
from .altcoin_basket_run import build_universe, eligibility_timeline, first_sustained_cross_section
from .altcoin_long_only_engine import (
    ANNUAL_DAYS, BASE_WEIGHT, BOOTSTRAP_BLOCK_DAYS, EVIDENCE_LABEL, INITIAL_CAPITAL_QUOTE,
    MOMENTUM_DAYS, PARTICIPATION_RATE, PROTOCOL_ID, REALISTIC_COST, REBALANCE_DAYS,
    REBALANCE_HOUR_UTC, REBALANCE_WEEKDAY, STRESS_COST, TOP_K, VOL_TARGET,
    VOL_WINDOW_DAYS, block_bootstrap, run_train, summary, weekly_decisions,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "normalized-basket"
OUTPUT = ROOT / "reports" / "altcoin-lomom-phase3"
REPORT = ROOT / "reports" / "ALTCOIN_LOMOM_PHASE3_TRAIN.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ledger_rows(records) -> list[dict]:
    rows = []
    for record in records:
        rows.append({
            "day_iso": utc_iso(record.day_ms), "decision_iso": utc_iso(record.decision_ms) if record.decision_ms is not None else "",
            "status": record.status, "symbols": "|".join(x.symbol for x in record.holdings),
            "weights": "|".join(f"{x.weight:.12f}" for x in record.holdings),
            "momenta": "|".join(f"{x.momentum:.12f}" for x in record.holdings),
            "participation_caps": "|".join(f"{x.participation_cap:.12f}" for x in record.holdings),
            "vol_multiplier": f"{record.multiplier:.12f}", "gross_return": f"{record.gross_return:.12f}",
            "funding_return": f"{record.funding_return:.12f}", "turnover": f"{record.turnover:.12f}",
            "net_realistic": f"{record.net_realistic:.12f}", "net_stress": f"{record.net_stress:.12f}",
            "equity_realistic": f"{record.equity_realistic:.12f}", "equity_stress": f"{record.equity_stress:.12f}",
            "violations": "|".join(record.violations),
        })
    return rows


def write_ledger(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def reconcile_ledger(path: Path, expected: dict, stress: bool = False) -> dict:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    net_key = "net_stress" if stress else "net_realistic"
    equity_key = "equity_stress" if stress else "equity_realistic"
    cost = STRESS_COST if stress else REALISTIC_COST
    actual = {
        "daily_equivalent_observations": len(rows),
        "scheduled_rebalances": sum(bool(row["decision_iso"]) for row in rows),
        "compounded_net_return": float(rows[-1][equity_key]) - 1.0,
        "turnover_sum": sum(float(row["turnover"]) for row in rows),
        "gross_return_sum": sum(float(row["gross_return"]) for row in rows),
        "funding_return_sum": sum(float(row["funding_return"]) for row in rows),
        "cost_drag": sum(float(row["turnover"]) for row in rows) * cost,
        "violation_count": sum(bool(row["violations"]) for row in rows),
        "net_arithmetic_sum": sum(float(row[net_key]) for row in rows),
    }
    for key in ("daily_equivalent_observations", "scheduled_rebalances", "compounded_net_return", "turnover_sum", "gross_return_sum", "funding_return_sum", "cost_drag", "violation_count"):
        if abs(float(actual[key]) - float(expected[key])) > 2e-9:
            raise ValueError(f"ledger reconciliation failed: {key}: {actual[key]} != {expected[key]}")
    return actual


def attribution(records) -> dict:
    symbols = defaultdict(float); quarters = defaultdict(float)
    for record in records:
        dt = datetime.fromtimestamp(record.day_ms / 1000, tz=timezone.utc)
        quarters[f"{dt.year}-Q{(dt.month-1)//3+1}"] += record.net_realistic
        total_weight = sum(x.weight for x in record.holdings)
        if total_weight:
            for holding in record.holdings:
                symbols[holding.symbol] += record.net_realistic * holding.weight / total_weight
    positive = sum(max(0.0, value) for value in symbols.values())
    max_share = max((max(0.0, value) / positive for value in symbols.values()), default=0.0) if positive else None
    return {"by_symbol": dict(sorted(symbols.items())), "positive_pnl_max_symbol_share": max_share, "by_quarter": dict(sorted(quarters.items())), "positive_quarters": sum(value > 0 for value in quarters.values()), "quarter_count": len(quarters)}


def train_gate(realistic: dict, stress: dict, bootstrap: dict, attrib: dict) -> dict:
    checks = {
        "observations_at_least_252": realistic["daily_equivalent_observations"] >= 252,
        "rebalances_at_least_50": realistic["scheduled_rebalances"] >= 50,
        "realistic_sharpe_at_least_0_75": realistic["net_sharpe"] is not None and realistic["net_sharpe"] >= .75,
        "bootstrap_lower_above_zero": bootstrap["ci95_low"] is not None and bootstrap["ci95_low"] > 0,
        "stress_compounded_positive": stress["compounded_net_return"] > 0,
        "max_drawdown_no_worse_than_minus_30pct": realistic["max_drawdown"] >= -.30,
        "symbol_positive_pnl_share_at_most_40pct": attrib["positive_pnl_max_symbol_share"] is not None and attrib["positive_pnl_max_symbol_share"] <= .40,
        "at_least_three_positive_quarters": attrib["positive_quarters"] >= 3,
        "zero_violations": realistic["violation_count"] == 0,
    }
    return {"scope": "TRAIN diagnostic only; prospective gate is not opened", "checks": checks, "verdict": "PASS" if all(checks.values()) else "FAIL"}


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    universe = build_universe()
    timeline = eligibility_timeline(universe)
    start = first_sustained_cross_section(timeline)
    if start is None: raise RuntimeError("no sustained eligible cross-section")
    decisions = weekly_decisions(start, HOLDOUT_START_MS)
    if not decisions: raise RuntimeError("no weekly decisions")
    start = decisions[0]
    config = {
        "protocol_id": PROTOCOL_ID, "evidence_label": EVIDENCE_LABEL, "run_scope": "DEVELOPMENT/TRAIN only",
        "train": [utc_iso(start), HOLDOUT_START_ISO], "basket": BASKET, "momentum_days": MOMENTUM_DAYS,
        "top_k": TOP_K, "pre_scaling_weight": BASE_WEIGHT, "rebalance_days": REBALANCE_DAYS,
        "rebalance": "Monday 00:00 UTC", "execution": "decision uses bars closed before t; execution at bar open t",
        "volatility": {"window_full_daily_returns": VOL_WINDOW_DAYS, "annualisation_days": ANNUAL_DAYS, "target": VOL_TARGET, "multiplier_bounds": [0, 1], "warmup": "cash until 30 complete causal shadow-portfolio daily returns"},
        "daily_aggregation": "UTC open-to-open compounded portfolio returns with actual funding",
        "bootstrap_block_days": BOOTSTRAP_BLOCK_DAYS, "cost_round_trip": {"realistic": REALISTIC_COST, "stress": STRESS_COST},
        "participation": {"rate": PARTICIPATION_RATE, "mechanic": "each target weight capped at 1% of prior closed hourly quote volume divided by current realistic-cost equity; residual is cash", "initial_capital_quote": INITIAL_CAPITAL_QUOTE},
        "search_points": 1, "survivorship_selection_bias": True,
    }
    write_json(OUTPUT / "config.json", config)
    hashes = {path.name: sha256(path) for path in sorted(DATA.glob("*")) if path.is_file()}
    write_json(OUTPUT / "input-hashes.json", hashes)
    records = run_train(universe, start, HOLDOUT_START_MS)
    rows = ledger_rows(records); write_ledger(OUTPUT / "ledger-train.csv", rows)
    realistic = summary(records); stress = summary(records, stress=True); bootstrap = block_bootstrap(records)
    attrib = attribution(records); gate = train_gate(realistic, stress, bootstrap, attrib)
    reconciliation = {"realistic": reconcile_ledger(OUTPUT / "ledger-train.csv", realistic), "stress": reconcile_ledger(OUTPUT / "ledger-train.csv", stress, True), "status": "PASS"}
    result = {"protocol_id": PROTOCOL_ID, "evidence_label": EVIDENCE_LABEL, "realistic": realistic, "stress": stress, "bootstrap": bootstrap, "attribution": attrib, "train_gate": gate, "reconciliation": reconciliation}
    write_json(OUTPUT / "train-result.json", result)
    report = f"""# ALT-LOMOM-002-A — Phase 3 DEVELOPMENT/TRAIN\n\n**Evidence:** {EVIDENCE_LABEL}. Fixed basket knowingly retains survivorship/selection bias.\n\n**Scope:** only `{utc_iso(start)}` to `< {HOLDOUT_START_ISO}`. No 2026+ data, prospective VALIDATION, sealed HOLDOUT, grid search, paper or live trading was accessed.\n\n## Frozen implementation\n\nMonday 00:00 UTC rebalance; 30-day momentum; top 4 at 25% before one common 20% volatility-target multiplier; 30 complete UTC daily shadow-portfolio returns with sqrt(365) annualisation; 30-day bootstrap blocks; 1% prior-hour quote-volume participation cap; 0.12% realistic and 0.20% stress turnover costs.\n\n## TRAIN result\n\n- realistic net Sharpe: `{realistic['net_sharpe']:.4f}`\n- realistic compounded return: `{realistic['compounded_net_return']:.2%}`\n- stress compounded return: `{stress['compounded_net_return']:.2%}`\n- max drawdown: `{realistic['max_drawdown']:.2%}`\n- bootstrap Sharpe CI95: `[{bootstrap['ci95_low']:.4f}; {bootstrap['ci95_high']:.4f}]`\n- observations / scheduled rebalances: `{realistic['daily_equivalent_observations']} / {realistic['scheduled_rebalances']}`\n- maximum symbol share of positive net PnL: `{attrib['positive_pnl_max_symbol_share']:.2%}`\n- constraint/data-boundary violations: `{realistic['violation_count']}`\n- ledger reconciliation: **{reconciliation['status']}**\n\n## Mechanical TRAIN diagnostic\n\n**{gate['verdict']}**. This is contaminated DEVELOPMENT/TRAIN evidence, not prospective confirmation. It cannot by itself authorize Phase 4, paper trading, or live trading.\n\nChecks: `{json.dumps(gate['checks'], sort_keys=True)}`.\n\nArtifacts: `config.json`, `input-hashes.json`, `ledger-train.csv`, and `train-result.json` in `reports/altcoin-lomom-phase3/`.\n"""
    REPORT.write_text(report, encoding="utf-8")
    print(json.dumps({"train_gate": gate["verdict"], "realistic": realistic, "stress": stress, "bootstrap": bootstrap}, indent=2))

if __name__ == "__main__": main()
