"""Phase B runner for ALT-XSMOM-001-B.

Exploratory fixed-basket evidence with survivorship/selection bias.

Order of operations is deliberate and must not be reordered:

1. Pre-HOLDOUT per-symbol data audit and eligibility gate.
2. Abort entirely if fewer than 5 symbols are eligible.
3. Freeze TRAIN / VALIDATION boundaries from coverage, before any PnL.
4. Sweep the preregistered grid on TRAIN, pick one primary by TRAIN net Sharpe.
5. Confirm that single primary once on VALIDATION, then run controls.

The HOLDOUT stays sealed: nothing in this module reads a timestamp at or after
2026-01-01T00:00:00Z.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from .altcoin_basket_data import (
    BASKET,
    COVERAGE_WINDOW_MS,
    DAY_MS,
    EVIDENCE_LABEL,
    HOLDOUT_START_ISO,
    HOLDOUT_START_MS,
    HOUR_MS,
    MIN_COVERAGE,
    MIN_CROSS_SECTION,
    MIN_LISTING_AGE_DAYS,
    MIN_LISTING_AGE_MS,
    PROTOCOL_ID,
    BasketBar,
    FundingEvent,
    assert_pre_holdout,
    audit_series,
    utc_iso,
    write_json,
)
from .altcoin_basket_engine import (
    COST_SCENARIOS,
    RANKING_HORIZONS_DAYS,
    REBALANCE_HOURS,
    SymbolSeries,
    block_bootstrap_sharpe,
    book_size,
    eligible_symbols,
    pnl_attribution,
    rank_symbols,
    run_configuration,
    summarise,
)

DATA_ROOT = Path("data")
REPORT_ROOT = Path("reports/altcoin-phase-b")

#: Primary selection metric, fixed before any result is seen.
PRIMARY_METRIC = "net_sharpe"
PRIMARY_COST_SCENARIO = "realistic_0_12pct"

#: TRAIN / VALIDATION split of the usable pre-HOLDOUT span. TEST is the sealed HOLDOUT.
TRAIN_FRACTION = 0.70


def load_series(symbol: str) -> tuple[list[BasketBar], list[FundingEvent]]:
    path = DATA_ROOT / "normalized-basket" / f"{symbol}-1h.csv"
    bars: list[BasketBar] = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            ts = int(row["open_time"])
            assert_pre_holdout(ts)
            bars.append(
                BasketBar(
                    ts=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    quote_volume=float(row["quote_volume"]),
                )
            )
    funding_path = DATA_ROOT / "normalized-basket" / f"{symbol}-funding.json"
    funding: list[FundingEvent] = []
    if funding_path.exists():
        for ts, rate in json.loads(funding_path.read_text(encoding="utf-8")):
            assert_pre_holdout(int(ts))
            funding.append(FundingEvent(int(ts), float(rate)))
    return bars, funding


def build_universe() -> dict[str, SymbolSeries]:
    universe: dict[str, SymbolSeries] = {}
    for symbol in BASKET:
        bars, funding = load_series(symbol)
        universe[symbol] = SymbolSeries.build(symbol, bars, funding)
    return universe


def per_symbol_audit(universe: dict[str, SymbolSeries]) -> dict:
    """Data audit plus the earliest timestamp each symbol could ever be eligible."""
    rows = {}
    for symbol in BASKET:
        item = universe[symbol]
        audit = audit_series(item.bars)
        earliest = (item.timestamps[0] + MIN_LISTING_AGE_MS) if item.timestamps else None
        rows[symbol] = {
            **audit,
            "funding_events": len(item.funding),
            "earliest_possible_eligibility": earliest,
            "earliest_possible_eligibility_iso": utc_iso(earliest) if earliest else None,
            "listing_age_rule_days": MIN_LISTING_AGE_DAYS,
            "coverage_rule": MIN_COVERAGE,
        }
    return rows


def eligibility_timeline(universe: dict[str, SymbolSeries], step_days: int = 7) -> list[dict]:
    """Weekly eligible-count curve used only to locate the usable span."""
    starts = [item.timestamps[0] for item in universe.values() if item.timestamps]
    if not starts:
        return []
    cursor = min(starts) + MIN_LISTING_AGE_MS
    timeline: list[dict] = []
    while cursor < HOLDOUT_START_MS:
        eligible, reasons = eligible_symbols(universe, cursor)
        timeline.append(
            {
                "ts": cursor,
                "iso": utc_iso(cursor),
                "eligible_count": len(eligible),
                "eligible": eligible,
                "excluded": reasons,
            }
        )
        cursor += step_days * DAY_MS
    return timeline


def first_sustained_cross_section(timeline: list[dict], required_weeks: int = 8) -> int | None:
    """First timestamp where >=5 symbols stay eligible for `required_weeks` consecutively."""
    run = 0
    for row in timeline:
        if row["eligible_count"] >= MIN_CROSS_SECTION:
            run += 1
            if run >= required_weeks:
                return timeline[timeline.index(row) - required_weeks + 1]["ts"]
        else:
            run = 0
    return None


def freeze_splits(start_ms: int) -> dict:
    """Split the usable pre-HOLDOUT span into TRAIN and VALIDATION.

    Both boundaries are derived from data coverage only and are fixed before any
    PnL is computed. TEST is the sealed HOLDOUT and is never touched here.
    """
    usable_end = HOLDOUT_START_MS
    span = usable_end - start_ms
    train_end = start_ms + int(span * TRAIN_FRACTION)
    # Align to the coarsest rebalance step so every grid point sees the same span.
    step = max(REBALANCE_HOURS) * HOUR_MS
    train_end -= train_end % step
    return {
        "train": {"start": start_ms, "end": train_end},
        "validation": {"start": train_end, "end": usable_end},
        "train_iso": [utc_iso(start_ms), utc_iso(train_end)],
        "validation_iso": [utc_iso(train_end), utc_iso(usable_end)],
        "train_days": (train_end - start_ms) / DAY_MS,
        "validation_days": (usable_end - train_end) / DAY_MS,
        "test": "SEALED HOLDOUT >= " + HOLDOUT_START_ISO,
        "train_fraction": TRAIN_FRACTION,
        "boundary_rule": "derived from coverage-based usable span, frozen before any PnL",
    }


def sweep(universe: dict[str, SymbolSeries], window: dict, label: str) -> list[dict]:
    """Evaluate every preregistered grid point on one window."""
    results: list[dict] = []
    for horizon in RANKING_HORIZONS_DAYS:
        for rebalance in REBALANCE_HOURS:
            periods = run_configuration(
                universe, window["start"], window["end"], horizon, rebalance
            )
            row = {
                "window": label,
                "ranking_horizon_days": horizon,
                "rebalance_hours": rebalance,
                "by_cost": {
                    name: summarise(periods, cost, rebalance) for name, cost in COST_SCENARIOS.items()
                },
            }
            results.append(row)
    return results


def primary_from_train(train_rows: list[dict]) -> dict:
    """Single primary configuration by TRAIN net Sharpe under the realistic cost."""
    ranked = sorted(
        train_rows,
        key=lambda row: (
            row["by_cost"][PRIMARY_COST_SCENARIO][PRIMARY_METRIC] is not None,
            row["by_cost"][PRIMARY_COST_SCENARIO][PRIMARY_METRIC] or float("-inf"),
        ),
        reverse=True,
    )
    return ranked[0]


def ledger_rows(periods, cost: float) -> list[dict]:
    rows: list[dict] = []
    for period in periods:
        if not period.legs:
            rows.append(
                {
                    "decision_iso": utc_iso(period.decision_ms),
                    "status": "skipped",
                    "reason": period.skipped_reason,
                    "eligible_count": len(period.eligible),
                    "eligible": "|".join(period.eligible),
                    "symbol": "",
                    "side": "",
                    "weight": "",
                    "entry_iso": "",
                    "exit_iso": "",
                    "entry_price": "",
                    "exit_price": "",
                    "leg_gross_return": "",
                    "leg_funding_return": "",
                    "momentum": "",
                    "volatility": "",
                    "period_net_return": "",
                }
            )
            continue
        net = period.net_return(cost)
        for leg in period.legs:
            rows.append(
                {
                    "decision_iso": utc_iso(period.decision_ms),
                    "status": "active",
                    "reason": "",
                    "eligible_count": len(period.eligible),
                    "eligible": "|".join(period.eligible),
                    "symbol": leg.symbol,
                    "side": leg.side,
                    "weight": f"{leg.weight:.10f}",
                    "entry_iso": utc_iso(leg.entry_ts),
                    "exit_iso": utc_iso(leg.exit_ts),
                    "entry_price": leg.entry_price,
                    "exit_price": leg.exit_price,
                    "leg_gross_return": f"{leg.gross_return:.10f}",
                    "leg_funding_return": f"{leg.funding_return:.10f}",
                    "momentum": f"{leg.momentum:.10f}",
                    "volatility": f"{leg.volatility:.10f}",
                    "period_net_return": f"{net:.10f}",
                }
            )
    return rows


def write_ledger(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def controls(universe: dict[str, SymbolSeries], window: dict, horizon: int, rebalance: int) -> dict:
    """Falsification controls on the confirmation window."""
    cost = COST_SCENARIOS[PRIMARY_COST_SCENARIO]

    def inverted(series, eligible, decision_ms, horizon_days):
        return list(reversed(rank_symbols(series, eligible, decision_ms, horizon_days)))

    baseline = run_configuration(universe, window["start"], window["end"], horizon, rebalance)
    reversed_periods = run_configuration(
        universe, window["start"], window["end"], horizon, rebalance, ranker=inverted
    )
    delayed = run_configuration(
        universe, window["start"], window["end"], horizon, rebalance, execution_delay_bars=1
    )
    zero_cost = summarise(baseline, 0.0, rebalance)
    return {
        "baseline": summarise(baseline, cost, rebalance),
        "sign_flipped_ranking": summarise(reversed_periods, cost, rebalance),
        "execution_delayed_one_bar": summarise(delayed, cost, rebalance),
        "zero_cost_reference": zero_cost,
        "interpretation": {
            "sign_flip": "a genuine cross-sectional effect should roughly invert when the ranking is inverted",
            "delay": "a fragile edge decays sharply when execution is pushed one hour later",
            "zero_cost": "gap between zero-cost and net shows how much of the result costs consume",
        },
    }


def main() -> None:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    universe = build_universe()

    audit = per_symbol_audit(universe)
    timeline = eligibility_timeline(universe)
    max_eligible = max((row["eligible_count"] for row in timeline), default=0)

    gate = {
        "protocol_id": PROTOCOL_ID,
        "evidence_label": EVIDENCE_LABEL,
        "holdout_start": HOLDOUT_START_ISO,
        "min_cross_section": MIN_CROSS_SECTION,
        "max_simultaneously_eligible": max_eligible,
        "gate_passed": max_eligible >= MIN_CROSS_SECTION,
    }
    write_json(REPORT_ROOT / "per-symbol-audit.json", audit)
    write_json(REPORT_ROOT / "eligibility-timeline.json", timeline)
    write_json(REPORT_ROOT / "gate.json", gate)

    if not gate["gate_passed"]:
        print(json.dumps({"aborted": "cross-section gate failed", **gate}, indent=2))
        return

    start_ms = first_sustained_cross_section(timeline)
    if start_ms is None:
        write_json(REPORT_ROOT / "gate.json", {**gate, "gate_passed": False, "reason": "no sustained cross-section"})
        print(json.dumps({"aborted": "no sustained cross-section"}, indent=2))
        return

    splits = freeze_splits(start_ms)
    write_json(REPORT_ROOT / "splits.json", splits)
    print("splits frozen:", json.dumps(splits["train_iso"] + splits["validation_iso"]), flush=True)

    train_rows = sweep(universe, splits["train"], "train")
    write_json(REPORT_ROOT / "train-grid.json", train_rows)

    primary = primary_from_train(train_rows)
    horizon = primary["ranking_horizon_days"]
    rebalance = primary["rebalance_hours"]
    write_json(
        REPORT_ROOT / "primary-selection.json",
        {
            "selected_on": "TRAIN only",
            "metric": PRIMARY_METRIC,
            "cost_scenario": PRIMARY_COST_SCENARIO,
            "ranking_horizon_days": horizon,
            "rebalance_hours": rebalance,
            "train_summary": primary["by_cost"],
            "grid_points_evaluated": len(train_rows),
            "note": "one configuration only; VALIDATION is used once for confirmation",
        },
    )
    print(f"primary: horizon={horizon}d rebalance={rebalance}h", flush=True)

    validation_periods = run_configuration(
        universe, splits["validation"]["start"], splits["validation"]["end"], horizon, rebalance
    )
    cost = COST_SCENARIOS[PRIMARY_COST_SCENARIO]
    validation_summary = {
        name: summarise(validation_periods, value, rebalance) for name, value in COST_SCENARIOS.items()
    }
    bootstrap = block_bootstrap_sharpe(validation_periods, cost, rebalance)
    attribution = pnl_attribution(validation_periods, cost)

    train_periods = run_configuration(
        universe, splits["train"]["start"], splits["train"]["end"], horizon, rebalance
    )
    write_ledger(REPORT_ROOT / "ledger-train.csv", ledger_rows(train_periods, cost))
    write_ledger(REPORT_ROOT / "ledger-validation.csv", ledger_rows(validation_periods, cost))

    control_results = controls(universe, splits["validation"], horizon, rebalance)

    write_json(
        REPORT_ROOT / "validation-result.json",
        {
            "protocol_id": PROTOCOL_ID,
            "evidence_label": EVIDENCE_LABEL,
            "configuration": {"ranking_horizon_days": horizon, "rebalance_hours": rebalance},
            "by_cost": validation_summary,
            "bootstrap_net_sharpe": bootstrap,
            "attribution": attribution,
            "controls": control_results,
            "train_reference": summarise(train_periods, cost, rebalance),
        },
    )
    print(json.dumps({"validation": validation_summary[PRIMARY_COST_SCENARIO], "bootstrap": bootstrap}, indent=2))


if __name__ == "__main__":
    main()
