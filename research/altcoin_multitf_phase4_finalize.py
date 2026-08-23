"""Finalization pipeline for ALTCOIN_MULTITF_005 Phase 4 Part 2.

Applies the frozen statistical contract to completed sweep results:
SPA across the complete valid search space, Deflated Sharpe Ratio using the
effective number of trials, Holm correction, seeded block-bootstrap confidence
intervals, topology-derived parameter neighbours, fee/slippage/funding stress,
temporal consistency, concentration, coverage and long/short gates, followed by
the pre-registered deterministic decision rule:

    rank candidates by the frozen protocol ordering
    (eligible, median fold Sharpe desc, aggregate Sharpe desc, net return desc,
     drawdown closest to zero first, configuration key asc);
    the first candidate passing EVERY mandatory gate is selected;
    several passers therefore resolve deterministically by that same ordering;
    zero passers resolve to NO_SELECTION. Criteria are never weakened.
"""
from __future__ import annotations

import csv
import json
import platform
import time
from pathlib import Path

from research.altcoin_multitf_gates import (
    ConfigMetrics,
    HOLM_P_LIMIT,
    DSR_PROBABILITY_LIMIT,
    NEIGHBOR_MIN_PROFITABLE_SHARE,
    SPA_P_LIMIT,
    TEMPORAL_MIN_POSITIVE_FOLDS,
    eligibility_report,
    is_eligible,
    neighbor_profitability,
    ordering_key,
    parameter_neighbors,
)
from research.altcoin_multitf_phase3 import Family, StrategyConfig, write_json_atomic
from research.altcoin_multitf_phase4 import Costs, FundingEvent
from research.altcoin_multitf_phase4_fast import IndicatorCache, evaluate_compact
from research.altcoin_multitf_phase4_runner import EXPECTED_GRID_COUNT, frozen_grid
from research.altcoin_multitf_phase4_sweep import (
    BOOTSTRAP_REPLICATES,
    INITIAL_EQUITY_PER_SYMBOL,
    SHORTLIST_SIZE,
    SPA_REPLICATES,
    SweepError,
    init_worker,
    load_all_rows,
)
from research.altcoin_multitf_statistics import (
    circular_block_bootstrap_mean_ci,
    deflated_sharpe_probability,
    holm_adjusted,
    newey_west_lrv,
    normal_cdf,
    nw_lag,
    spa_pvalues,
)


def _metrics_from_row(row: dict[str, object]) -> ConfigMetrics:
    return ConfigMetrics(
        config_key=str(row["key"]),
        valid=bool(row["valid"]),
        zero_trade=bool(row["zero_trade"]),
        invalid_reason=row["invalid_reason"] if "invalid_reason" in row else None,
        trades=int(str(row["trades"])),
        net_pnl=float(str(row["net_pnl"])),
        net_return=float(str(row["net_return"])),
        mean_trade_return=float(str(row["mean_trade_return"])),
        daily_sharpe=None if row["daily_sharpe"] is None else float(str(row["daily_sharpe"])),
        annualized_sharpe=None if row["annualized_sharpe"] is None else float(str(row["annualized_sharpe"])),
        median_fold_sharpe=float(str(row["median_fold_sharpe"])),
        fold_sharpes=tuple(float(v) for v in row["fold_sharpes"]),
        fold_net_returns=tuple(float(v) for v in row["fold_net_returns"]),
        positive_folds=int(str(row["positive_folds"])),
        max_drawdown=float(str(row["max_drawdown"])),
        active_assets=int(str(row["active_assets"])),
        asset_names=tuple(str(v) for v in row["asset_names"]),
        max_asset_positive_share=float(str(row["max_asset_positive_share"])),
        long_trades=int(str(row["long_trades"])),
        short_trades=int(str(row["short_trades"])),
        long_net_pnl=float(str(row["long_net_pnl"])),
        short_net_pnl=float(str(row["short_net_pnl"])),
        ending_equity=float(str(row["ending_equity"])),
        rejected_orders_total=int(str(row["rejected_orders_total"])),
        missing_bars=int(str(row["missing_bars"])),
        funding_events=int(str(row["funding_events"])),
        daily_returns=tuple(float(v) for v in row["daily_returns"]),
    )


def _stress_scenarios(funding: tuple[FundingEvent, ...]) -> dict[str, tuple[Costs | None, tuple[FundingEvent, ...] | None]]:
    """None means 'use the baseline value' for that component."""
    return {
        "fee_double": (Costs(8.0, 2.0), None),
        "slippage_triple": (Costs(4.0, 6.0), None),
        "funding_double": (Costs(), tuple(FundingEvent(e.timestamp_ms, e.rate * 2.0) for e in funding)),
        "funding_flipped_double": (Costs(), tuple(FundingEvent(e.timestamp_ms, -e.rate * 2.0) for e in funding)),
    }


def run_stress_tests(config: StrategyConfig, datasets: dict) -> dict[str, dict[str, float]]:
    """Re-evaluate one configuration under adverse cost/funding scenarios."""
    cache = IndicatorCache(max_entries=12)
    tf = config.signal_tf_minutes
    base_funding = next(iter(datasets.values()))["funding"]
    results: dict[str, dict[str, float]] = {}
    for name, (costs, scenario_funding) in _stress_scenarios(base_funding).items():
        total_net = 0.0
        trades = 0
        valid_all = True
        for symbol in sorted(datasets):
            dataset = datasets[symbol]
            evaluation = evaluate_compact(
                config,
                dataset["execution"],
                dataset["signals"][tf],
                dataset["regime"],
                dataset["funding"] if scenario_funding is None else scenario_funding,
                dataset["rules"],
                costs=costs,
                prevalidated=True,
                cache=cache,
                symbol=symbol,
                signal_tf=tf,
            )
            if not evaluation.valid:
                raise SweepError(f"stress scenario {name} produced an invalid evaluation for {config.key}")
            total_net += sum(trade.net_pnl for trade in evaluation.trades)
            trades += len(evaluation.trades)
        del valid_all
        results[name] = {
            "net_return": total_net / (INITIAL_EQUITY_PER_SYMBOL * len(UNIVERSE_SYMBOLS)),
            "trades": float(trades),
            "pass": total_net > 0,
        }
    return results


def finalize_selection(artifacts_dir: Path, cache_dir: Path, inputs_root: Path | None = None) -> dict:
    started = time.time()
    rows = load_all_rows(cache_dir)
    if len(rows) != EXPECTED_GRID_COUNT:
        raise SweepError(f"expected {EXPECTED_GRID_COUNT} result rows, found {len(rows)}")
    by_key = {str(row["key"]): row for row in rows}
    grid = frozen_grid()
    if set(by_key) != {config.key for config in grid}:
        raise SweepError("result keys do not match the frozen grid")

    invalid_rows = [row for row in rows if not row["valid"]]
    zero_trade_rows = [row for row in rows if row["valid"] and row["zero_trade"]]
    active_rows = [row for row in rows if row["valid"] and not row["zero_trade"]]
    invalid_reason_counts: dict[str, int] = {}
    for row in invalid_rows:
        reason = str(row["invalid_reason"])
        invalid_reason_counts[reason] = invalid_reason_counts.get(reason, 0) + 1

    lag = nw_lag(len(active_rows[0]["daily_returns"])) if active_rows else 10
    spa = spa_pvalues({str(row["key"]): list(row["daily_returns"]) for row in active_rows}, replicates=SPA_REPLICATES, seed=20250306, lag=lag)
    naive_p = {}
    for row in active_rows:
        series = list(row["daily_returns"])
        mean = sum(series) / len(series)
        lrv = newey_west_lrv(series, lag)
        stat = None if lrv <= 0 else (len(series) ** 0.5) * mean / (lrv**0.5)
        naive_p[str(row["key"])] = 1.0 if stat is None else 1.0 - min(1.0, max(0.0, normal_cdf(stat)))
    holm = holm_adjusted(naive_p)

    sr_values = [float(row["daily_sharpe"]) for row in active_rows if row["daily_sharpe"] is not None]
    n_trials = len(active_rows) + len(zero_trade_rows)
    sr_mean = sum(sr_values) / len(sr_values) if sr_values else 0.0
    sr_variance = sum((v - sr_mean) ** 2 for v in sr_values) / len(sr_values) if sr_values else 0.0
    dsr_probs = {}
    for row in active_rows:
        key = str(row["key"])
        sr = float(row["daily_sharpe"])
        dsr_probs[key] = deflated_sharpe_probability(sr, list(row["daily_returns"]), n_trials, sr_variance)

    statistics_payload = {
        str(row["key"]): {
            "spa_p": spa.get(str(row["key"]), 1.0),
            "naive_p": naive_p.get(str(row["key"]), 1.0),
            "holm_p": holm.get(str(row["key"]), 1.0),
            "dsr_probability": dsr_probs.get(str(row["key"]), 0.0),
            "daily_sharpe": row["daily_sharpe"],
        }
        for row in rows
        if row["valid"]
    }
    write_json_atomic(
        artifacts_dir / "statistical-tests.json",
        {
            "method": {"spa": "Hansen 2005 stationary bootstrap, screened consistent p-values", "dsr": "Bailey-Lopez de Prado deflated Sharpe", "holm": "step-down"},
            "spa_replicates": SPA_REPLICATES,
            "bootstrap_seed": 20250305,
            "spa_seed": 20250306,
            "n_trials_dsr": n_trials,
            "sharpe_variance_across_trials": sr_variance,
            "nw_lag": lag,
            "results": statistics_payload,
        },
    )

    metrics_by_key = {str(row["key"]): _metrics_from_row(row) for row in rows}
    neighbors = parameter_neighbors(grid)
    eligible_keys = sorted(
        (key for key in by_key if is_eligible(metrics_by_key[key])),
        key=lambda key: ordering_key(metrics_by_key[key]),
    )
    eligibility_table = {
        key: {"eligibility": eligibility_report(metrics_by_key[key]), "ordering_rank": None} for key in sorted(by_key)
    }
    for rank, key in enumerate(eligible_keys, 1):
        eligibility_table[key]["ordering_rank"] = rank  # type: ignore[union-attr]
    write_json_atomic(artifacts_dir / "eligibility-table.json", {"eligible_count": len(eligible_keys), "table": eligibility_table})

    rejection_log: list[dict[str, object]] = []
    winner_key = None
    examined = 0
    for key in eligible_keys[:SHORTLIST_SIZE]:
        examined += 1
        metrics = metrics_by_key[key]
        stats = statistics_payload[key]
        failures: list[str] = []
        if stats["spa_p"] > SPA_P_LIMIT:
            failures.append("spa_p_above_limit")
        if stats["dsr_probability"] < DSR_PROBABILITY_LIMIT:
            failures.append("dsr_below_limit")
        if stats["holm_p"] > HOLM_P_LIMIT:
            failures.append("holm_p_above_limit")
        neighbor_check = neighbor_profitability(key, neighbors, metrics_by_key)
        if not neighbor_check["gate_pass"]:
            failures.append("neighbors_share_below_60pct")
        if metrics.median_fold_sharpe <= 0 or metrics.positive_folds < TEMPORAL_MIN_POSITIVE_FOLDS:
            failures.append("temporal_consistency_failed")
        if metrics.long_trades == 0 or metrics.short_trades == 0 or metrics.long_net_pnl <= 0 or metrics.short_net_pnl <= 0:
            failures.append("long_short_gate_failed")
        bootstrap_summary = None
        stress_summary = None
        config = next(item for item in grid if item.key == key)
        if not failures and inputs_root is not None:
            from research.altcoin_multitf_phase4_sweep import init_worker as _init

            try:
                _init(str(inputs_root))
            except SweepError as exc:
                raise SweepError(f"cannot run finalist verification: {exc}") from exc
            from research.altcoin_multitf_phase4_sweep import _WORKER

            datasets = _WORKER["datasets"]
            events = []
            for symbol in sorted(datasets):
                dataset = datasets[symbol]
                evaluation = evaluate_compact(
                    config,
                    dataset["execution"],
                    dataset["signals"][config.signal_tf_minutes],
                    dataset["regime"],
                    dataset["funding"],
                    dataset["rules"],
                    prevalidated=True,
                    cache=_WORKER["cache"],
                    symbol=symbol,
                    signal_tf=config.signal_tf_minutes,
                )
                for trade in evaluation.trades:
                    events.append((trade.entry_time_ms, symbol, trade.exit_time_ms, trade.net_pnl))
            events.sort()
            denominator = INITIAL_EQUITY_PER_SYMBOL * len(UNIVERSE_SYMBOLS)
            bootstrap_summary = circular_block_bootstrap_mean_ci(
                [event[3] for event in events],
                replicates=BOOTSTRAP_REPLICATES,
                seed=20250305,
            )
            bootstrap_summary["scaled_lower"] = bootstrap_summary["lower"] / denominator
            bootstrap_summary["scaled_upper"] = bootstrap_summary["upper"] / denominator
            if bootstrap_summary["lower"] <= 0:
                failures.append("bootstrap_ci_lower_not_positive")
            stress_summary = run_stress_tests(config, datasets)
            failed_stress = sorted(name for name, outcome in stress_summary.items() if not outcome["pass"])
            if failed_stress:
                failures.extend(f"stress_{name}_failed" for name in failed_stress)
        entry = {
            "key": key,
            "statistics": stats,
            "neighbor_check": neighbor_check,
            "fold_sharpes": list(metrics.fold_sharpes),
            "bootstrap": bootstrap_summary,
            "stress": stress_summary,
            "failures": failures,
            "passes_all_gates": not failures,
        }
        rejection_log.append(entry)
        if not failures and winner_key is None:
            winner_key = key
            break
    if eligible_keys and examined < len(eligible_keys) and winner_key is None:
        rejection_log.append({"note": f"{len(eligible_keys)-examined} further eligible candidates beyond shortlist were not examined because every examined candidate failed at least one gate", "count": len(eligible_keys) - examined})

    dossier = {
        "tie_break_rule": "pre-registered protocol ordering; first full passer wins",
        "eligible_candidates": len(eligible_keys),
        "examined_candidates": examined,
        "candidate_reports": rejection_log,
    }
    write_json_atomic(artifacts_dir / "selection-dossier.json", dossier)

    verdict = {
        "decision": "SELECT" if winner_key else "NO_SELECTION",
        "selected_key": winner_key,
        "rule": "exactly one candidate after pre-registered tie-breaking, else NO_SELECTION",
    }
    write_json_atomic(artifacts_dir / "verdict.json", verdict)

    summary_fields = [
        "key", "family", "signal_tf_minutes", "fast_window", "slow_window", "entry_threshold", "exit_threshold", "stop_atr", "take_atr", "max_holding_bars",
        "valid", "zero_trade", "invalid_reason", "trades", "net_pnl", "net_return", "daily_sharpe", "annualized_sharpe", "median_fold_sharpe", "positive_folds",
        "max_drawdown", "active_assets", "max_asset_positive_share", "long_trades", "short_trades", "long_net_pnl", "short_net_pnl", "missing_bars", "funding_events",
    ]
    with (artifacts_dir / "development-metrics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(rows, key=lambda item: str(item["key"])):
            compact = {field: row.get(field) for field in summary_fields}
            writer.writerow(compact)

    metadata = {
        "rows": len(rows),
        "invalid": len(invalid_rows),
        "invalid_reason_counts": invalid_reason_counts,
        "valid_zero_trade": len(zero_trade_rows),
        "valid_active": len(active_rows),
        "eligible": len(eligible_keys),
        "spa_replicates": SPA_REPLICATES,
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "elapsed_seconds": time.time() - started,
        "decision": verdict["decision"],
    }
    write_json_atomic(artifacts_dir / "run-metadata.json", metadata)
    return {"decision": verdict["decision"], "selected_key": winner_key, "eligible": len(eligible_keys), "examined": examined}
