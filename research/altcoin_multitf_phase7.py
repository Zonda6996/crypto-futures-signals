"""ALT-MULTITF-007 deterministic sweep runner ("Definitive One-Shot").

Implements the frozen protocol `docs/ALTCOIN_MULTITF_007_FROZEN_PROTOCOL.md`:
exactly 8 canonical long-only daily-trend configurations evaluated once over the
full DECIDE window 2021-01-01 .. 2026-06-30 (accounting; engine span includes full
indicator warmup from each symbol's earliest acquired history). The causal engine,
cost model and statistical gate stack are inherited unchanged from ALT-MULTITF-005/006.
Temporal robustness substitutes for a missing out-of-sample interval: eleven calendar
half-year folds, gate = positive annualized Sharpe in >=7 of them and median fold
Sharpe > 0. There is no confirmation stage; the monitor reserve (2026-07..) is never
read by this module.
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

from research.altcoin_multitf_gates import (
    ConfigMetrics,
    compute_metrics,
    eligibility_report,
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

PROTOCOL_ID = "ALT-MULTITF-007"
PROTOCOL_DOC = Path("docs/ALTCOIN_MULTITF_007_FROZEN_PROTOCOL.md")
ARTIFACTS = Path("reports/artifacts/altcoin-multitf-007")
RULES_PATH = ARTIFACTS / "input" / "exchange-rules-frozen.json"
SUPPLEMENT_ROOT = "altcoin-multitf-006-supplement"

DECIDE_START_MS = 1_609_459_200_000          # 2021-01-01T00:00:00Z
DECIDE_END_EXCLUSIVE_MS = 1_782_864_000_000  # 2026-07-01T00:00:00Z

SEED_SWEEP = 20260907
SEED_BOOTSTRAP = 20260908
SEED_SPA = 20260909

EXPECTED_GRID_COUNT = 8
SPA_REPLICATES = 1000
BOOTSTRAP_REPLICATES = 2000
SHORTLIST_SIZE = 8
INITIAL_EQUITY_PER_SYMBOL = 10_000.0
DENOMINATOR = INITIAL_EQUITY_PER_SYMBOL * len(UNIVERSE_SYMBOLS)

HERITAGE_TRIALS = 5_832 + 192 + 8  # every configuration ever evaluated by 005+006+007
TEMPORAL_MIN_POSITIVE_FOLDS = 7

SMA_PAIRS = ((20, 100), (50, 200))
ENTRY_THRESHOLDS = (0.005, 0.01)
HOLDING_BARS = (2880, 11_520)  # 10 / 40 days of 5m execution bars

# Eleven calendar half-year folds, boundaries at Jan-01/Jul-01 00:00 UTC.
HALF_YEAR_BOUNDARIES_MS = (
    1_609_459_200_000,  # 2021-01-01
    1_625_097_600_000,  # 2021-07-01
    1_640_995_200_000,  # 2022-01-01
    1_656_633_600_000,  # 2022-07-01
    1_672_531_200_000,  # 2023-01-01
    1_688_169_600_000,  # 2023-07-01
    1_704_067_200_000,  # 2024-01-01
    1_719_792_000_000,  # 2024-07-01
    1_735_689_600_000,  # 2025-01-01
    1_751_328_000_000,  # 2025-07-01
    1_767_225_600_000,  # 2026-01-01
    1_782_864_000_000,  # 2026-07-01
)
FOLD_BOUNDS_007 = list(zip(HALF_YEAR_BOUNDARIES_MS[:-1], HALF_YEAR_BOUNDARIES_MS[1:]))

SWEEP_SCHEMA = "altcoin-multitf-007-sweep-v1"

PRIOR_INPUTS = {
    "primary_archive_sha256": "665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d",
    "supplement_archive_sha256": "a753585a11beb7bad74f9262920324fe8315a681b6dd108db072790bad47bd5b",
    "supplement_v2_archive_sha256": "487046fad5659e427075ca2b2b676bb3213da85276848129ba5eb21f00d10c56",
}
EXCHANGE_INFO_RAW_SHA256 = "3eb3bcf246495fb0e9e99a38f7d6c4cd741ced5f4256b461d3cf8643df5b2daf"


class Phase7Error(RuntimeError):
    pass


def frozen_grid_007() -> tuple[StrategyConfig, ...]:
    configs = []
    seen = set()
    for fast, slow in SMA_PAIRS:
        if fast >= slow:
            raise Phase7Error(f"invalid sma pair: {(fast, slow)}")
        for entry_threshold in ENTRY_THRESHOLDS:
            for max_holding_bars in HOLDING_BARS:
                config = StrategyConfig(
                    Family.A,
                    1440,
                    10080,
                    fast,
                    slow,
                    entry_threshold,
                    0.0,
                    3.0,
                    6.0,
                    max_holding_bars,
                    "long",
                )
                if config.key in seen:
                    raise Phase7Error(f"configuration key collision: {config.key}")
                seen.add(config.key)
                configs.append(config)
    configs.sort(key=lambda item: item.key)
    if len(configs) != EXPECTED_GRID_COUNT:
        raise Phase7Error(f"frozen 007 grid mismatch: {len(configs)} != {EXPECTED_GRID_COUNT}")
    return tuple(configs)


# ---------------------------------------------------------------------------
# dataset loading (supplement v2 normalized layer + frozen freeze-time rules)


def _read_compact(path: Path, end_exclusive_ms: int | None) -> CompactSeries:
    if not path.is_file():
        raise Phase7Error(f"missing normalized series: {path}")
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
        raise Phase7Error(f"empty series: {path}")
    series = build_compact(bars)
    try:
        validate_compact(series)
    except ValueError as exc:
        raise Phase7Error(f"invalid series {path}: {exc}") from exc
    return series


def load_frozen_rules() -> dict:
    if sha256_file(RULES_PATH) != "3109eeae512270d1fad0db5f28ffe3265d6a18f0e660c6275356f0cbd1a4b0a6":
        raise Phase7Error("frozen rules file hash mismatch")
    payload = json.loads(RULES_PATH.read_text())
    from research.altcoin_multitf_phase3 import ExchangeRules

    rules = {}
    for symbol, values in sorted(payload.items()):
        max_qty = values.get("max_qty")
        rules[symbol] = ExchangeRules(
            float(values["tick_size"]),
            float(values["step_size"]),
            float(values["min_qty"]),
            float(values["min_notional"]),
            None if max_qty is None else float(max_qty),
        )
    missing = [s for s in UNIVERSE_SYMBOLS if s not in rules]
    if missing:
        raise Phase7Error(f"frozen rules missing symbols: {missing}")
    return rules


class Phase7Datasets:
    def __init__(self, merged_root: Path) -> None:
        self.merged_root = merged_root.resolve()
        self.rules = load_frozen_rules()
        base = self.merged_root / SUPPLEMENT_ROOT
        self.datasets = {}
        klines_base = base / "development" / "normalized" / "klines"
        funding_base = base / "development" / "normalized" / "funding"
        end_exclusive_ms = DECIDE_END_EXCLUSIVE_MS
        for symbol in UNIVERSE_SYMBOLS:
            execution = _read_compact(klines_base / symbol / f"{symbol}-5m.csv.gz", end_exclusive_ms)
            signal = _read_compact(klines_base / symbol / f"{symbol}-1d.csv.gz", end_exclusive_ms)
            regime = _read_compact(klines_base / symbol / f"{symbol}-1w.csv.gz", end_exclusive_ms)
            funding_path = funding_base / symbol / f"{symbol}-funding.csv.gz"
            events = []
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
        builder = IndicatorCache(max_entries=64, windows=(20, 50, 100, 200))
        for symbol, data in self.datasets.items():
            sig_entry = builder.signal_entry(id(data["signal"]), data["signal"])
            reg_entry = builder.regime_entry(id(data["regime"]), data["regime"])
            self.entries[symbol] = (sig_entry, reg_entry)

    def evaluate_config(self, config: StrategyConfig) -> dict[str, Evaluation]:
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
                decision_start_ms=DECIDE_START_MS,
            )
            kept = tuple(trade for trade in raw.trades if trade.entry_time_ms >= DECIDE_START_MS)
            evaluations[symbol] = Evaluation(config.key, raw.valid, kept, raw.ending_equity, raw.diagnostics)
        return evaluations


# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def run_sweep(merged_root: Path, cache_dir: Path) -> dict:
    started = time.time()
    grid = frozen_grid_007()
    cache_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = cache_dir / "checkpoint-007.json"
    completed: dict[str, dict] = {}
    if checkpoint_path.is_file():
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if payload.get("schema") != SWEEP_SCHEMA or payload.get("seed") != SEED_SWEEP or payload.get("grid_count") != EXPECTED_GRID_COUNT or payload.get("window") != [DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS]:
            raise Phase7Error("resume rejected: 007 checkpoint identity mismatch")
        completed = payload.get("rows", {})
    print(f"007 sweep start: pending={len(grid)-len(completed)}", flush=True)
    if len(completed) < len(grid):
        datasets = Phase7Datasets(merged_root)
        pending = [c for c in grid if c.key not in completed]
        for index, config in enumerate(pending, 1):
            evaluations = datasets.evaluate_config(config)
            metrics = compute_metrics(
                config.key,
                evaluations,
                initial_equity=INITIAL_EQUITY_PER_SYMBOL,
                window_start_ms=DECIDE_START_MS,
                window_end_ms=DECIDE_END_EXCLUSIVE_MS,
                fold_bounds_override=FOLD_BOUNDS_007,
            )
            completed[config.key] = row_from_metrics(metrics, config)
            write_json_atomic(checkpoint_path, {
                "schema": SWEEP_SCHEMA, "seed": SEED_SWEEP, "grid_count": EXPECTED_GRID_COUNT,
                "window": [DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS], "rows": completed,
            })
            print(f"007 sweep {index}/{len(pending)} done elapsed={time.time()-started:.0f}s", flush=True)
    marker = {"expected": EXPECTED_GRID_COUNT, "completed": len(completed), "complete": len(completed) == EXPECTED_GRID_COUNT, "elapsed_seconds": time.time() - started}
    write_json_atomic(cache_dir / "completion-007.json", marker)
    if not marker["complete"]:
        raise Phase7Error("decide sweep incomplete")
    return marker


def load_rows(cache_dir: Path) -> dict[str, dict]:
    payload = json.loads((cache_dir / "checkpoint-007.json").read_text(encoding="utf-8"))
    rows = payload["rows"]
    if len(rows) != EXPECTED_GRID_COUNT:
        raise Phase7Error("unexpected decide row count")
    return rows


def _metrics_from_row(row: dict) -> ConfigMetrics:
    metric_fields = {f for f in ConfigMetrics.__dataclass_fields__}
    fields = {k: v for k, v in row.items() if k in metric_fields}
    fields["config_key"] = row["key"]
    fields["fold_sharpes"] = tuple(fields["fold_sharpes"])
    fields["fold_net_returns"] = tuple(fields["fold_net_returns"])
    fields["asset_names"] = tuple(fields["asset_names"])
    fields["daily_returns"] = tuple(fields["daily_returns"])
    return ConfigMetrics(**fields)


def _neighbors(grid: list[StrategyConfig]) -> dict[str, set[str]]:
    """Neighbors differ in exactly one frozen axis: sma_pair | entry | holding."""
    by_key = {c.key: c for c in grid}

    def make(pair: tuple[int, int], entry: float, holding: int) -> StrategyConfig:
        return StrategyConfig(Family.A, 1440, 10080, pair[0], pair[1], entry, 0.0, 3.0, 6.0, holding, "long")

    neighbors: dict[str, set[str]] = {key: set() for key in by_key}
    for key, config in by_key.items():
        pair = (config.fast_window, config.slow_window)
        variants = []
        for other_pair in SMA_PAIRS:
            variants.append(make(other_pair, config.entry_threshold, config.max_holding_bars))
        for other_entry in ENTRY_THRESHOLDS:
            variants.append(make(pair, other_entry, config.max_holding_bars))
        for other_holding in HOLDING_BARS:
            variants.append(make(pair, config.entry_threshold, other_holding))
        for variant in variants:
            if variant.key in by_key and variant.key != key:
                neighbors[key].add(variant.key)
    return neighbors


def _stress_net(datasets: Phase7Datasets, config: StrategyConfig, scenario: str) -> float:
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
            decision_start_ms=DECIDE_START_MS,
        )
        total += sum(t.net_pnl for t in raw.trades if t.entry_time_ms >= DECIDE_START_MS)
    return total


def _maker_track_net(datasets: Phase7Datasets, config: StrategyConfig) -> float:
    total = 0.0
    for symbol in UNIVERSE_SYMBOLS:
        data = datasets.datasets[symbol]
        raw = evaluate_compact(
            config,
            data["execution"],
            data["signal"],
            data["regime"],
            data["funding"],
            data["rules"],
            costs=Costs(2.0, 1.0),
            prevalidated=True,
            signal_entry=datasets.entries[symbol][0],
            regime_entry=datasets.entries[symbol][1],
            decision_start_ms=DECIDE_START_MS,
        )
        total += sum(t.net_pnl for t in raw.trades if t.entry_time_ms >= DECIDE_START_MS)
    return total


def heritage_sharpe_variance(extra_values: list[float]) -> dict:
    """Published per-configuration daily Sharpes of 005+006 plus current values."""
    values = list(extra_values)
    sources = [
        ("005", Path("reports/artifacts/altcoin-multitf-005-phase4/development-metrics.csv")),
        ("006", Path("reports/artifacts/altcoin-multitf-006/development-metrics.csv")),
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


def input_manifest(repo_commit: str) -> dict:
    protocol_hash = sha256_file(PROTOCOL_DOC)
    rules_hash = sha256_file(RULES_PATH)
    manifest = {
        "protocol_id": PROTOCOL_ID,
        "repo_source_commit": repo_commit,
        "frozen_protocol_document": PROTOCOL_DOC.name,
        "frozen_protocol_sha256": protocol_hash,
        "freeze_proof_commit": "f0628f5",
        "prior_inputs": PRIOR_INPUTS,
        "exchange_info_freeze_snapshot": {
            "source_url": "https://www.binance.com/fapi/v1/exchangeInfo",
            "raw_sha256": EXCHANGE_INFO_RAW_SHA256,
            "rules_file": str(RULES_PATH),
            "rules_sha256": rules_hash,
        },
        "windows_utc": {
            "engine_span_start": "earliest acquired history per symbol",
            "decide": ["2021-01-01T00:00:00Z", "2026-07-01T00:00:00Z"],
            "monitor_reserve": ["2026-07-01T00:00:00Z", None],
        },
        "universe_used": list(UNIVERSE_SYMBOLS),
        "selection_policy": "single-pass decision; no confirmation stage; monitor reserve never read",
    }
    write_json_atomic(ARTIFACTS / "input-manifest.json", manifest)
    return manifest


def finalize(merged_root: Path, cache_dir: Path) -> dict:
    started = time.time()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    rows = load_rows(cache_dir)
    grid = list(frozen_grid_007())
    by_key = {c.key: c for c in grid}
    invalid = [k for k, r in rows.items() if not r["valid"]]
    zero = [k for k, r in rows.items() if r["valid"] and r["zero_trade"]]
    active_keys = sorted(k for k, r in rows.items() if r["valid"] and not r["zero_trade"])
    write_json_atomic(ARTIFACTS / "sweep-progress.json", json.loads((cache_dir / "checkpoint-007.json").read_text(encoding="utf-8")))
    csv_excluded = {"daily_returns", "fold_sharpes", "fold_net_returns", "asset_names"}
    with (ARTIFACTS / "development-metrics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        header = [k for k in rows[active_keys[0]] if k not in csv_excluded] if active_keys else ["key"]
        writer.writerow(header)
        for key in sorted(rows):
            row = rows[key]
            writer.writerow([row[h] for h in header])
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
    trials = len([k for k, r in rows.items() if r["valid"]])
    sr_values = [rows[k]["daily_sharpe"] for k in active_keys if rows[k]["daily_sharpe"] is not None]
    sr_mean = sum(sr_values) / len(sr_values) if sr_values else 0.0
    sr_var = sum((v - sr_mean) ** 2 for v in sr_values) / len(sr_values) if sr_values else 0.0
    dsr = {
        k: deflated_sharpe_probability(rows[k]["daily_sharpe"], rows[k]["daily_returns"], trials, sr_var)
        for k in active_keys
    }
    heritage = heritage_sharpe_variance(sr_values)
    heritage_dsr = {
        k: deflated_sharpe_probability(rows[k]["daily_sharpe"], rows[k]["daily_returns"], HERITAGE_TRIALS, heritage["variance"])
        for k in active_keys
    }
    statistics_payload = {
        k: {
            "spa_p": spa.get(k, 1.0), "naive_p": naive.get(k, 1.0), "holm_p": holm.get(k, 1.0),
            "dsr_probability": dsr.get(k, 0.0), "heritage_dsr_probability_n6032": heritage_dsr.get(k, 0.0),
        }
        for k in sorted(rows)
        if rows[k]["valid"]
    }
    write_json_atomic(ARTIFACTS / "statistics.json", {
        "method": {"spa": "Hansen 2005 screened consistent", "dsr": "Bailey-Lopez de Prado", "holm": "step-down"},
        "spa_replicates": SPA_REPLICATES, "spa_seed": SEED_SPA, "bootstrap_seed": SEED_BOOTSTRAP,
        "n_trials_dsr": trials, "sharpe_variance_across_trials": sr_var, "nw_lag": lag,
        "heritage_report_only": {"n_trials": HERITAGE_TRIALS, **{k: v for k, v in heritage.items()}},
        "results": statistics_payload,
    })

    metrics_by_key = {k: _metrics_from_row(rows[k]) for k in rows}
    neighbors = _neighbors(grid)
    eligible = sorted(
        (k for k in rows if is_eligible(metrics_by_key[k])),
        key=lambda k: ordering_key(metrics_by_key[k]),
    )
    write_json_atomic(ARTIFACTS / "eligibility-table.json", {
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
        if m.median_fold_sharpe <= 0 or m.positive_folds < TEMPORAL_MIN_POSITIVE_FOLDS:
            failures.append("temporal_consistency_failed")
        if failures:
            reports.append({"key": key, "failures": failures})
            continue
        if datasets is None:
            datasets = Phase7Datasets(merged_root)
        config = by_key[key]
        events = []
        for symbol in UNIVERSE_SYMBOLS:
            ev = datasets.evaluate_config(config)[symbol]
            events.extend((t.entry_time_ms, symbol, t.exit_time_ms, t.net_pnl) for t in ev.trades)
        events.sort()
        boot = circular_block_bootstrap_mean_ci([e[3] for e in events], replicates=BOOTSTRAP_REPLICATES, seed=SEED_BOOTSTRAP)
        boot["scaled_lower"] = boot["lower"] / DENOMINATOR
        stress = {name: {"net_return": _stress_net(datasets, config, name) / DENOMINATOR} for name in ("fee_double", "slippage_triple", "funding_double", "funding_flipped_double")}
        for name, out in stress.items():
            out["pass"] = out["net_return"] > 0
        failed_stress = sorted(n for n, o in stress.items() if not o["pass"])
        maker_net = _maker_track_net(datasets, config)
        if boot["lower"] <= 0:
            failures.append("bootstrap_ci_lower_not_positive")
        failures.extend(f"stress_{n}_failed" for n in failed_stress)
        reports.append({
            "key": key, "bootstrap": boot, "stress": stress,
            "maker_track_report_only": {"net_return": maker_net / DENOMINATOR},
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
        verdict["consequence"] = "altcoin multitf trend line closed permanently"
    write_json_atomic(ARTIFACTS / "verdict-final.json", verdict)
    write_json_atomic(ARTIFACTS / "run-metadata.json", {
        "rows": len(rows), "invalid": len(invalid), "zero_trade": len(zero), "active": len(active_keys),
        "eligible": len(eligible), "examined": examined, "elapsed_seconds": time.time() - started,
        "python": sys.version.split()[0], "seeds": {"sweep": SEED_SWEEP, "bootstrap": SEED_BOOTSTRAP, "spa": SEED_SPA},
    })
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-grid", action="store_true")
    parser.add_argument("--inputs-root", type=Path, default=Path(r"D:\alt-multitf-005-data\inputs"))
    parser.add_argument("--cache-dir", type=Path, default=Path(r"D:\alt-multitf-005-data\phase7-cache"))
    parser.add_argument("--stage", choices=("sweep", "finalize", "all"), required=False)
    args = parser.parse_args(argv)
    if args.validate_grid:
        grid = frozen_grid_007()
        print(json.dumps({"count": len(grid), "first_key": grid[0].key, "seed": SEED_SWEEP}, sort_keys=True))
        return 0
    merged_root = args.inputs_root / "merged"
    repo_commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    if args.stage in ("sweep", "all"):
        print(json.dumps(run_sweep(merged_root, args.cache_dir), sort_keys=True))
    if args.stage in ("finalize", "all"):
        input_manifest(repo_commit)
        print(json.dumps(finalize(merged_root, args.cache_dir), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
