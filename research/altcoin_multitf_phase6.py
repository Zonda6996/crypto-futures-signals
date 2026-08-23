"""ALT-MULTITF-006 deterministic sweep runner (protocol H1 "Daily trend").

Implements the frozen protocol `docs/ALTCOIN_MULTITF_006_FROZEN_PROTOCOL.md`:
192 configurations, DEV window = calendar 2024 (accounting; engine span includes full
indicator warmup from earliest acquired history), CONFIRM window = 2025-01..2026-06 for
the mandatory re-validation of the unique DEV winner. The causal engine, cost model and
statistical gate stack are inherited unchanged from ALT-MULTITF-005.

CONFIRM-window data may only be *acquired*; its metrics are computed exclusively inside
the confirmation stage after a DEV winner exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from research.altcoin_multitf_gates import (
    ConfigMetrics,
    compute_metrics,
    eligibility_report,
    fold_bounds,
    is_eligible,
    neighbor_profitability,
    ordering_key,
)
from research.altcoin_multitf_inputs import UNIVERSE_SYMBOLS
from research.altcoin_multitf_phase3 import Family, StrategyConfig, write_json_atomic
from research.altcoin_multitf_phase4 import Costs, Evaluation, FundingEvent
from research.altcoin_multitf_phase4_fast import (
    CompactSeries,
    IndicatorCache,
    build_compact,
    evaluate_compact,
    validate_compact,
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

PROTOCOL_ID = "ALT-MULTITF-006"
PROTOCOL_DOC = Path("docs/ALTCOIN_MULTITF_006_FROZEN_PROTOCOL.md")
ARTIFACTS = Path("reports/artifacts/altcoin-multitf-006")
SUPPLEMENT_ROOT = "altcoin-multitf-006-supplement"

DEV_START_MS = 1_735_689_600_000          # 2024-01-01T00:00:00Z
DEV_END_EXCLUSIVE_MS = 1_767_225_600_000  # 2025-01-01T00:00:00Z
CONFIRM_START_MS = 1_767_225_600_000      # 2025-01-01T00:00:00Z
CONFIRM_END_EXCLUSIVE_MS = 1_782_864_000_000  # 2026-07-01T00:00:00Z

SEED_SWEEP = 20260823
SEED_BOOTSTRAP = 20260824
SEED_SPA = 20260825

EXPECTED_GRID_COUNT = 192
CHUNK_SIZE = 24
SPA_REPLICATES = 1000
BOOTSTRAP_REPLICATES = 2000
SHORTLIST_SIZE = 25
INITIAL_EQUITY_PER_SYMBOL = 10_000.0
DENOMINATOR = INITIAL_EQUITY_PER_SYMBOL * len(UNIVERSE_SYMBOLS)

SWEEP_SCHEMA = "altcoin-multitf-006-sweep-v1"


class Phase6Error(RuntimeError):
    pass


def frozen_grid_006() -> tuple[StrategyConfig, ...]:
    configs = []
    seen = set()
    for fast in (10, 20):
        for slow in (50, 100, 200):
            if fast >= slow:
                continue
            for entry_threshold in (0.01, 0.02):
                for stop_atr in (2.0, 3.0):
                    for take_atr in (4.0, 6.0):
                        for max_holding_bars in (2880, 5760):
                            for side in ("long", "both"):
                                config = StrategyConfig(
                                    Family.A,
                                    1440,
                                    10080,
                                    fast,
                                    slow,
                                    entry_threshold,
                                    0.0,
                                    stop_atr,
                                    take_atr,
                                    max_holding_bars,
                                    side,
                                )
                                if config.key in seen:
                                    raise Phase6Error(f"configuration key collision: {config.key}")
                                seen.add(config.key)
                                configs.append(config)
    configs.sort(key=lambda item: item.key)
    if len(configs) != EXPECTED_GRID_COUNT:
        raise Phase6Error(f"frozen 006 grid mismatch: {len(configs)} != {EXPECTED_GRID_COUNT}")
    return tuple(configs)


# ---------------------------------------------------------------------------
# dataset loading (supplement v2 normalized layer)


def _read_compact(path: Path, end_exclusive_ms: int | None) -> CompactSeries:
    import csv
    import gzip

    if not path.is_file():
        raise Phase6Error(f"missing normalized series: {path}")
    bars = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            open_ms = int(row["open_time_ms"])
            if end_exclusive_ms is not None and open_ms >= end_exclusive_ms:
                continue
            bars.append(
                __import__("research.altcoin_multitf_phase3", fromlist=["Candle"]).Candle(
                    open_ms,
                    int(row["close_time_ms"]),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row["volume"]),
                )
            )
    if not bars:
        raise Phase6Error(f"empty series: {path}")
    series = build_compact(bars)
    try:
        validate_compact(series)
    except ValueError as exc:
        raise Phase6Error(f"invalid series {path}: {exc}") from exc
    return series


class Phase6Datasets:
    def __init__(self, merged_root: Path, end_exclusive_ms: int) -> None:
        self.merged_root = merged_root.resolve()
        self.end_exclusive_ms = end_exclusive_ms
        base = self.merged_root / SUPPLEMENT_ROOT
        rules_payload = json.loads((base / "metadata" / "supplement2.exchange-rules.json").read_text())
        from research.altcoin_multitf_phase3 import ExchangeRules

        self.rules = {}
        for symbol, values in sorted(rules_payload.items()):
            max_qty = values.get("max_qty")
            self.rules[symbol] = ExchangeRules(
                float(values["tick_size"]),
                float(values["step_size"]),
                float(values["min_qty"]),
                float(values["min_notional"]),
                None if max_qty is None else float(max_qty),
            )
        missing = [s for s in UNIVERSE_SYMBOLS if s not in self.rules]
        if missing:
            raise Phase6Error(f"rules missing symbols: {missing}")
        self.datasets = {}
        klines_base = base / "development" / "normalized" / "klines"
        funding_base = base / "development" / "normalized" / "funding"
        for symbol in UNIVERSE_SYMBOLS:
            execution = _read_compact(klines_base / symbol / f"{symbol}-5m.csv.gz", end_exclusive_ms)
            signal = _read_compact(klines_base / symbol / f"{symbol}-1d.csv.gz", end_exclusive_ms)
            regime = _read_compact(klines_base / symbol / f"{symbol}-1w.csv.gz", end_exclusive_ms)
            funding_path = funding_base / symbol / f"{symbol}-funding.csv.gz"
            events = []
            import csv
            import gzip

            with gzip.open(funding_path, "rt", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    ts = int(row["funding_time_ms"])
                    if ts >= end_exclusive_ms:
                        continue
                    events.append(FundingEvent(ts, float(row["funding_rate"])))
            self.datasets[symbol] = {
                "execution": execution,
                "signal": signal,
                "regime": regime,
                "funding": tuple(sorted(events, key=lambda e: e.timestamp_ms)),
                "rules": self.rules[symbol],
            }
        self.entries = {}
        builder = IndicatorCache(max_entries=64, windows=(10, 20, 50, 100, 200))
        for symbol, data in self.datasets.items():
            sig_entry = builder.signal_entry(id(data["signal"]), data["signal"])
            reg_entry = builder.regime_entry(id(data["regime"]), data["regime"])
            self.entries[symbol] = (sig_entry, reg_entry)

    def evaluate_config(self, config: StrategyConfig, window_start_ms: int) -> dict[str, Evaluation]:
        evaluations: dict[str, Evaluation] = {}
        for symbol in UNIVERSE_SYMBOLS:
            data = self.datasets[symbol]
            sig_entry, reg_entry = self.entries[symbol]
            raw = evaluate_compact(
                config,
                data["execution"],
                data["signal"],
                data["regime"],
                data["funding"],
                data["rules"],
                prevalidated=True,
                signal_entry=sig_entry,
                regime_entry=reg_entry,
                decision_start_ms=window_start_ms,
            )
            kept = tuple(trade for trade in raw.trades if trade.entry_time_ms >= window_start_ms)
            evaluations[symbol] = Evaluation(config.key, raw.valid, kept, raw.ending_equity, raw.diagnostics)
        return evaluations


def row_from_metrics(metrics: ConfigMetrics, config: StrategyConfig) -> dict[str, object]:
    return {
        "key": metrics.config_key,
        "family": config.family.value,
        "signal_tf_minutes": config.signal_tf_minutes,
        "regime_tf_minutes": config.regime_tf_minutes,
        "fast_window": config.fast_window,
        "slow_window": config.slow_window,
        "entry_threshold": config.entry_threshold,
        "stop_atr": config.stop_atr,
        "take_atr": config.take_atr,
        "max_holding_days": config.max_holding_bars // 288,
        "side": config.side,
        "valid": metrics.valid,
        "zero_trade": metrics.zero_trade,
        "invalid_reason": metrics.invalid_reason,
        "trades": metrics.trades,
        "net_pnl": metrics.net_pnl,
        "net_return": metrics.net_pnl / DENOMINATOR,
        "mean_trade_return": metrics.mean_trade_return,
        "daily_sharpe": metrics.daily_sharpe,
        "annualized_sharpe": metrics.annualized_sharpe,
        "median_fold_sharpe": metrics.median_fold_sharpe,
        "fold_sharpes": list(metrics.fold_sharpes),
        "fold_net_returns": list(metrics.fold_net_returns),
        "positive_folds": metrics.positive_folds,
        "max_drawdown": metrics.max_drawdown,
        "active_assets": metrics.active_assets,
        "asset_names": list(metrics.asset_names),
        "max_asset_positive_share": metrics.max_asset_positive_share,
        "long_trades": metrics.long_trades,
        "short_trades": metrics.short_trades,
        "long_net_pnl": metrics.long_net_pnl,
        "short_net_pnl": metrics.short_net_pnl,
        "ending_equity": metrics.ending_equity,
        "rejected_orders_total": metrics.rejected_orders_total,
        "missing_bars": metrics.missing_bars,
        "funding_events": metrics.funding_events,
        "daily_returns": list(metrics.daily_returns),
    }


def run_sweep_dev(merged_root: Path, cache_dir: Path) -> dict:
    started = time.time()
    grid = frozen_grid_006()
    cache_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = cache_dir / "checkpoint-dev.json"
    completed: dict[str, dict] = {}
    if checkpoint_path.is_file():
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if payload.get("schema") != SWEEP_SCHEMA or payload.get("seed") != SEED_SWEEP or payload.get("grid_count") != EXPECTED_GRID_COUNT:
            raise Phase6Error("resume rejected: 006 checkpoint identity mismatch")
        completed = payload.get("rows", {})
    print(f"006 sweep start: pending={len(grid)-len(completed)}", flush=True)
    if len(completed) < len(grid):
        datasets = Phase6Datasets(merged_root, DEV_END_EXCLUSIVE_MS)
        pending = [c for c in grid if c.key not in completed]
        for index, config in enumerate(pending, 1):
            evaluations = datasets.evaluate_config(config, DEV_START_MS)
            metrics = compute_metrics(
                config.key,
                evaluations,
                initial_equity=INITIAL_EQUITY_PER_SYMBOL,
                window_start_ms=DEV_START_MS,
                window_end_ms=DEV_END_EXCLUSIVE_MS,
            )
            completed[config.key] = row_from_metrics(metrics, config)
            if index % CHUNK_SIZE == 0 or index == len(pending):
                write_json_atomic(checkpoint_path, {"schema": SWEEP_SCHEMA, "seed": SEED_SWEEP, "grid_count": EXPECTED_GRID_COUNT, "rows": completed})
                print(f"006 sweep {index}/{len(pending)} done elapsed={time.time()-started:.0f}s", flush=True)
    marker = {"expected": EXPECTED_GRID_COUNT, "completed": len(completed), "complete": len(completed) == EXPECTED_GRID_COUNT, "elapsed_seconds": time.time() - started}
    write_json_atomic(cache_dir / "completion-dev.json", marker)
    if not marker["complete"]:
        raise Phase6Error("dev sweep incomplete")
    return marker


def load_rows(cache_dir: Path) -> dict[str, dict]:
    payload = json.loads((cache_dir / "checkpoint-dev.json").read_text(encoding="utf-8"))
    rows = payload["rows"]
    if len(rows) != EXPECTED_GRID_COUNT:
        raise Phase6Error("unexpected dev row count")
    return rows


def _metrics_from_row(row: dict) -> ConfigMetrics:
    fields = dict(row)
    fields["fold_sharpes"] = tuple(fields["fold_sharpes"])
    fields["fold_net_returns"] = tuple(fields["fold_net_returns"])
    fields["asset_names"] = tuple(fields["asset_names"])
    fields["daily_returns"] = tuple(fields["daily_returns"])
    return ConfigMetrics(**fields)


def _neighbors(grid: list[StrategyConfig]) -> dict[str, set[str]]:
    by_key = {c.key: c for c in grid}
    neighbors = {key: set() for key in by_key}
    axes = ("fast_window", "slow_window", "entry_threshold", "stop_atr", "take_atr", "max_holding_bars", "side")
    values = {
        "fast_window": [10, 20],
        "slow_window": [50, 100, 200],
        "entry_threshold": [0.01, 0.02],
        "stop_atr": [2.0, 3.0],
        "take_atr": [4.0, 6.0],
        "max_holding_bars": [2880, 5760],
        "side": ["long", "both"],
    }
    for key, config in by_key.items():
        for axis in axes:
            for value in values[axis]:
                if getattr(config, axis) == value:
                    continue
                kwargs = {a: getattr(config, a) for a in axes}
                kwargs[axis] = value
                try:
                    variant = StrategyConfig(Family.A, 1440, 10080, kwargs["fast_window"], kwargs["slow_window"], kwargs["entry_threshold"], 0.0, kwargs["stop_atr"], kwargs["take_atr"], kwargs["max_holding_bars"], kwargs["side"])
                except ValueError:
                    continue
                if variant.key in by_key:
                    neighbors[key].add(variant.key)
    return neighbors


def _stress_net(datasets: Phase6Datasets, config: StrategyConfig, scenario: str, window_start_ms: int, window_end_ms: int) -> float:
    costs_map = {
        "fee_double": Costs(8.0, 2.0),
        "slippage_triple": Costs(4.0, 6.0),
        "funding_double": Costs(),
        "funding_flipped_double": Costs(),
    }
    total = 0.0
    for symbol in UNIVERSE_SYMBOLS:
        data = datasets.datasets[symbol]
        funding = data["funding"]
        if scenario == "funding_double":
            funding = tuple(FundingEvent(e.timestamp_ms, e.rate * 2.0) for e in funding)
        elif scenario == "funding_flipped_double":
            funding = tuple(FundingEvent(e.timestamp_ms, -e.rate * 2.0) for e in funding)
        raw = evaluate_compact(
            config,
            data["execution"],
            data["signal"],
            data["regime"],
            funding,
            data["rules"],
            costs=costs_map[scenario],
            prevalidated=True,
            signal_entry=datasets.entries[symbol][0],
            regime_entry=datasets.entries[symbol][1],
            decision_start_ms=window_start_ms,
        )
        total += sum(t.net_pnl for t in raw.trades if t.entry_time_ms >= window_start_ms)
    return total


def finalize_dev(merged_root: Path, cache_dir: Path, artifacts: Path) -> dict:
    started = time.time()
    artifacts.mkdir(parents=True, exist_ok=True)
    rows = load_rows(cache_dir)
    grid = list(frozen_grid_006())
    by_key = {c.key: c for c in grid}
    invalid = [k for k, r in rows.items() if not r["valid"]]
    zero = [k for k, r in rows.items() if r["valid"] and r["zero_trade"]]
    active_keys = sorted(k for k, r in rows.items() if r["valid"] and not r["zero_trade"])

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
    sr_values = [rows[k]["daily_sharpe"] for k in active_keys if rows[k]["daily_sharpe"] is not None]
    trials = len([k for k, r in rows.items() if r["valid"]])
    sr_mean = sum(sr_values) / len(sr_values) if sr_values else 0.0
    sr_var = sum((v - sr_mean) ** 2 for v in sr_values) / len(sr_values) if sr_values else 0.0
    dsr = {
        k: deflated_sharpe_probability(rows[k]["daily_sharpe"], rows[k]["daily_returns"], trials, sr_var)
        for k in active_keys
    }
    statistics_payload = {
        k: {"spa_p": spa.get(k, 1.0), "naive_p": naive.get(k, 1.0), "holm_p": holm.get(k, 1.0), "dsr_probability": dsr.get(k, 0.0)}
        for k in sorted(rows)
        if rows[k]["valid"]
    }
    write_json_atomic(artifacts / "statistics-dev.json", {
        "method": {"spa": "Hansen 2005 screened consistent", "dsr": "Bailey-Lopez de Prado", "holm": "step-down"},
        "spa_replicates": SPA_REPLICATES, "spa_seed": SEED_SPA, "bootstrap_seed": SEED_BOOTSTRAP,
        "n_trials_dsr": trials, "sharpe_variance_across_trials": sr_var, "nw_lag": lag,
        "results": statistics_payload,
    })

    metrics_by_key = {k: _metrics_from_row(rows[k]) for k in rows}
    neighbors = _neighbors(grid)
    eligible = sorted(
        (k for k in rows if is_eligible(metrics_by_key[k])),
        key=lambda k: ordering_key(metrics_by_key[k]),
    )
    write_json_atomic(artifacts / "eligibility-table-dev.json", {
        "eligible_count": len(eligible),
        "ordering": [{"rank": i + 1, "key": k} for i, k in enumerate(eligible[:SHORTLIST_SIZE])],
        "table": {k: eligibility_report(metrics_by_key[k]) for k in sorted(rows)},
    })

    reports = []
    winner = None
    examined = 0
    datasets = None
    for key in eligible[:SHORTLIST_SIZE]:
        examined += 1
        m = metrics_by_key[key]
        st = statistics_payload[key]
        failures = []
        if st["spa_p"] > 0.05:
            failures.append("spa_p_above_limit")
        if st["dsr_probability"] < 0.95:
            failures.append("dsr_below_limit")
        if st["holm_p"] > 0.05:
            failures.append("holm_p_above_limit")
        ncheck = neighbor_profitability(key, neighbors, metrics_by_key)
        if not ncheck["gate_pass"]:
            failures.append("neighbors_share_below_60pct")
        if m.median_fold_sharpe <= 0 or m.positive_folds < 4:
            failures.append("temporal_consistency_failed")
        if m.long_trades == 0 or m.short_trades == 0 or m.long_net_pnl <= 0 or m.short_net_pnl <= 0:
            if by_key[key].side == "both":
                failures.append("long_short_gate_failed")
        if failures:
            reports.append({"key": key, "failures": failures}); continue
        if datasets is None:
            datasets = Phase6Datasets(merged_root, DEV_END_EXCLUSIVE_MS)
        config = by_key[key]
        events = []
        for symbol in UNIVERSE_SYMBOLS:
            ev = datasets.evaluate_config(config, DEV_START_MS)[symbol]
            events.extend((t.entry_time_ms, symbol, t.exit_time_ms, t.net_pnl) for t in ev.trades)
        events.sort()
        boot = circular_block_bootstrap_mean_ci([e[3] for e in events], replicates=BOOTSTRAP_REPLICATES, seed=SEED_BOOTSTRAP)
        boot["scaled_lower"] = boot["lower"] / DENOMINATOR
        stress = {name: {"net_return": _stress_net(datasets, config, name, DEV_START_MS, DEV_END_EXCLUSIVE_MS) / DENOMINATOR} for name in ("fee_double", "slippage_triple", "funding_double", "funding_flipped_double")}
        for name, out in stress.items():
            out["pass"] = out["net_return"] > 0
        failed_stress = sorted(n for n, o in stress.items() if not o["pass"])
        if boot["lower"] <= 0:
            failures.append("bootstrap_ci_lower_not_positive")
        failures.extend(f"stress_{n}_failed" for n in failed_stress)
        reports.append({"key": key, "bootstrap": boot, "stress": stress, "failures": failures, "passes_all_gates": not failures})
        if not failures and winner is None:
            winner = key
            break
    write_json_atomic(artifacts / "selection-dossier-dev.json", {
        "tie_break_rule": "pre-registered ordering; rank-1 full passer wins",
        "eligible_candidates": len(eligible), "examined": examined, "reports": reports,
    })
    verdict = {"stage": "DEV", "decision": "CANDIDATE_FOUND" if winner else "NO_SELECTION", "candidate_key": winner}
    write_json_atomic(artifacts / "verdict-dev.json", verdict)
    write_json_atomic(artifacts / "run-metadata-dev.json", {
        "rows": len(rows), "invalid": len(invalid), "zero_trade": len(zero), "active": len(active_keys),
        "eligible": len(eligible), "examined": examined, "elapsed_seconds": time.time() - started,
        "python": sys.version.split()[0],
    })
    return verdict


def confirm_winner(merged_root: Path, artifacts: Path) -> dict:
    candidate = json.loads((artifacts / "verdict-dev.json").read_text())["candidate_key"]
    if candidate is None:
        final = {"stage": "FINAL", "decision": "NO_SELECTION", "reason": "no DEV candidate"}
        write_json_atomic(artifacts / "verdict-final.json", final)
        return final
    datasets = Phase6Datasets(merged_root, CONFIRM_END_EXCLUSIVE_MS)
    config = next(c for c in frozen_grid_006() if c.key == candidate)
    evaluations = datasets.evaluate_config(config, CONFIRM_START_MS)
    metrics = compute_metrics(
        candidate, evaluations, initial_equity=INITIAL_EQUITY_PER_SYMBOL,
        window_start_ms=CONFIRM_START_MS, window_end_ms=CONFIRM_END_EXCLUSIVE_MS,
    )
    events = []
    for symbol in UNIVERSE_SYMBOLS:
        for t in evaluations[symbol].trades:
            events.append((t.entry_time_ms, symbol, t.exit_time_ms, t.net_pnl))
    events.sort()
    boot = circular_block_bootstrap_mean_ci([e[3] for e in events], replicates=BOOTSTRAP_REPLICATES, seed=SEED_BOOTSTRAP)
    checks = {
        "trades_ge_100": metrics.trades >= 100,
        "net_return_positive": metrics.net_return > 0,
        "annualized_sharpe_above_0_5": (metrics.annualized_sharpe or 0.0) > 0.5,
        "drawdown_within_limit": metrics.max_drawdown >= -0.25,
        "coverage_ge_6_assets": metrics.active_assets >= 6,
        "bootstrap_ci_lower_positive": boot["lower"] > 0,
    }
    passed = all(checks.values())
    report = {
        "candidate_key": candidate,
        "metrics": {
            "trades": metrics.trades, "net_return": metrics.net_return,
            "annualized_sharpe": metrics.annualized_sharpe, "median_fold_sharpe": metrics.median_fold_sharpe,
            "max_drawdown": metrics.max_drawdown, "active_assets": metrics.active_assets,
            "long_net": metrics.long_net_pnl, "short_net": metrics.short_net_pnl,
            "positive_folds": metrics.positive_folds, "fold_sharpes": list(metrics.fold_sharpes),
        },
        "bootstrap": boot, "checks": checks, "passed": passed,
    }
    write_json_atomic(artifacts / "confirmation-report.json", report)
    final = {"stage": "FINAL", "decision": "SELECT" if passed else "NO_SELECTION", "selected_key": candidate if passed else None}
    write_json_atomic(artifacts / "verdict-final.json", final)
    return final


def input_manifest_v2(supplement2_archive: Path, merged_root: Path, artifacts: Path) -> dict:
    repo_commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    prior = json.loads(Path("reports/artifacts/altcoin-multitf-005-phase4/input-manifest.json").read_text())

    def sha(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    manifest = {
        "protocol_id": PROTOCOL_ID,
        "repo_source_commit": repo_commit,
        "frozen_protocol_document": PROTOCOL_DOC.name,
        "frozen_protocol_sha256": sha(PROTOCOL_DOC),
        "prior_inputs": {
            "primary_archive_sha256": prior["primary_archive"]["sha256"],
            "supplement_archive_sha256": prior["supplement_archive"]["sha256"],
            "merged_tree_digest_005": prior["merged_tree_digest"],
        },
        "supplement_v2_archive": {
            "root_name": SUPPLEMENT_ROOT,
            "size": supplement2_archive.stat().st_size,
            "sha256": sha(supplement2_archive),
        },
        "windows_utc": {
            "engine_span_start": "earliest acquired history (2020-02)",
            "dev": ["2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"],
            "confirm": ["2025-01-01T00:00:00Z", "2026-07-01T00:00:00Z"],
        },
        "universe_used": list(UNIVERSE_SYMBOLS),
        "evaluation_sealed_policy": "confirm metrics computed only inside the confirmation stage",
    }
    write_json_atomic(artifacts / "input-manifest-v2.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-grid", action="store_true")
    parser.add_argument("--inputs-root", type=Path, default=Path(r"D:\alt-multitf-005-data\inputs"))
    parser.add_argument("--cache-dir", type=Path, default=Path(r"D:\alt-multitf-005-data\phase6-cache"))
    parser.add_argument("--supplement2-archive", type=Path, default=Path(r"D:\alt-multitf-005-data\supplement2-ws\release\altcoin-multitf-006-supplement.tar.gz"))
    parser.add_argument("--stage", choices=("sweep", "finalize", "confirm", "all"), required=False)
    args = parser.parse_args(argv)
    if args.validate_grid:
        grid = frozen_grid_006()
        print(json.dumps({"count": len(grid), "first_key": grid[0].key, "seed": SEED_SWEEP}, sort_keys=True))
        return 0
    merged_root = args.inputs_root / "merged"
    if args.stage in ("sweep", "all"):
        print(json.dumps(run_sweep_dev(merged_root, args.cache_dir), sort_keys=True))
    if args.stage in ("finalize", "all"):
        input_manifest_v2(args.supplement2_archive, merged_root, ARTIFACTS)
        print(json.dumps(finalize_dev(merged_root, args.cache_dir, ARTIFACTS), sort_keys=True))
    if args.stage in ("confirm", "all"):
        print(json.dumps(confirm_winner(merged_root, ARTIFACTS), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
