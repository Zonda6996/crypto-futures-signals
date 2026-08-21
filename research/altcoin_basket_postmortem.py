"""Read-only post-mortem for the failed frozen ALT-XSMOM-001-B experiment."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .altcoin_basket_data import HOLDOUT_START_MS, HoldoutSealedError

COST = 0.0012
CONCENTRATION_LIMIT = 0.25
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports" / "altcoin-phase-b"
OUTPUT = SOURCE / "diagnostics"


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def load_ledger(path: Path) -> list[dict]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    for row in rows:
        for key in ("decision_iso", "entry_iso", "exit_iso"):
            if row.get(key) and _ms(row[key]) >= HOLDOUT_START_MS:
                raise HoldoutSealedError(f"HOLDOUT row in {path}: {key}={row[key]}")
    return rows


def diagnose(rows: Iterable[dict], cost: float = COST) -> dict:
    rows = list(rows)
    periods: dict[str, list[dict]] = defaultdict(list)
    skipped = defaultdict(int)
    for row in rows:
        if row["status"] != "active":
            skipped[row.get("reason") or "unspecified"] += 1
        else:
            periods[row["decision_iso"]].append(row)

    by_symbol = defaultdict(lambda: {"gross": 0.0, "funding": 0.0, "cost": 0.0, "net": 0.0, "long_net": 0.0, "short_net": 0.0, "observations": 0})
    by_leg = defaultdict(lambda: {"gross": 0.0, "funding": 0.0, "cost": 0.0, "net": 0.0})
    by_quarter = defaultdict(lambda: {"gross": 0.0, "funding": 0.0, "cost": 0.0, "net": 0.0, "periods": 0})
    turnover = []
    period_net_sum = 0.0
    concentration_breaches = 0
    missing_funding = 0

    for decision, legs in sorted(periods.items()):
        weights = [abs(float(x["weight"])) for x in legs]
        turn = sum(weights)
        turnover.append(turn)
        if max(weights, default=0.0) > CONCENTRATION_LIMIT:
            concentration_breaches += 1
        dt = datetime.fromisoformat(decision.replace("Z", "+00:00"))
        quarter = f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"
        by_quarter[quarter]["periods"] += 1
        calculated_period_net = 0.0
        for row, weight in zip(legs, weights):
            gross = weight * float(row["leg_gross_return"])
            funding = weight * float(row["leg_funding_return"])
            fee = weight * cost
            net = gross + funding - fee
            side = "long" if int(row["side"]) == 1 else "short"
            symbol = by_symbol[row["symbol"]]
            symbol["gross"] += gross; symbol["funding"] += funding; symbol["cost"] += fee
            symbol["net"] += net; symbol[f"{side}_net"] += net; symbol["observations"] += 1
            by_leg[side]["gross"] += gross; by_leg[side]["funding"] += funding
            by_leg[side]["cost"] += fee; by_leg[side]["net"] += net
            by_quarter[quarter]["gross"] += gross; by_quarter[quarter]["funding"] += funding
            by_quarter[quarter]["cost"] += fee; by_quarter[quarter]["net"] += net
            calculated_period_net += net
            if row.get("leg_funding_return", "") == "":
                missing_funding += 1
        recorded = float(legs[0]["period_net_return"])
        if abs(calculated_period_net - recorded) > 1e-8:
            raise ValueError(f"period reconciliation failed at {decision}")
        period_net_sum += recorded

    gross = sum(x["gross"] for x in by_leg.values())
    funding = sum(x["funding"] for x in by_leg.values())
    cost_drag = sum(x["cost"] for x in by_leg.values())
    net = gross + funding - cost_drag
    return {
        "active_periods": len(periods), "skipped_rows_by_reason": dict(sorted(skipped.items())),
        "gross_return_sum": gross, "funding_return_sum": funding, "cost_drag": cost_drag,
        "net_return_sum": net, "recorded_period_net_sum": period_net_sum,
        "turnover": {"sum": sum(turnover), "mean": sum(turnover) / len(turnover) if turnover else 0.0, "min": min(turnover, default=0.0), "max": max(turnover, default=0.0)},
        "legs": dict(sorted(by_leg.items())), "symbols": dict(sorted(by_symbol.items())),
        "quarters": dict(sorted(by_quarter.items())), "missing_funding_observations": missing_funding,
        "concentration": {"limit": CONCENTRATION_LIMIT, "breach_periods": concentration_breaches, "breach_share": concentration_breaches / len(periods) if periods else 0.0},
    }


def reconcile(result: dict, frozen: dict, split: str) -> None:
    expected = frozen["train_reference"] if split == "train" else frozen["by_cost"]["realistic_0_12pct"]
    keys = ("active_periods", "gross_return_sum", "funding_return_sum", "cost_drag", "turnover_sum")
    actual = {**result, "turnover_sum": result["turnover"]["sum"]}
    for key in keys:
        if abs(float(actual[key]) - float(expected[key])) > 1e-8:
            raise ValueError(f"{split} reconciliation failed for {key}: {actual[key]} != {expected[key]}")


def run(source: Path = SOURCE, output: Path = OUTPUT) -> dict:
    frozen = json.loads((source / "validation-result.json").read_text())
    report = {"protocol_id": "ALT-XSMOM-001-B", "evidence_label": frozen["evidence_label"], "cost_round_trip": COST, "holdout_status": "SEALED", "splits": {}}
    for split in ("train", "validation"):
        result = diagnose(load_ledger(source / f"ledger-{split}.csv"))
        reconcile(result, frozen, split)
        report["splits"][split] = result
    output.mkdir(parents=True, exist_ok=True)
    (output / "postmortem.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    for split, result in report["splits"].items():
        with (output / f"symbol-attribution-{split}.csv").open("w", newline="") as f:
            fields = ["symbol", "gross", "funding", "cost", "net", "long_net", "short_net", "observations"]
            writer = csv.DictWriter(f, fields); writer.writeheader()
            for symbol, values in result["symbols"].items(): writer.writerow({"symbol": symbol, **values})
    return report


if __name__ == "__main__":
    run()
