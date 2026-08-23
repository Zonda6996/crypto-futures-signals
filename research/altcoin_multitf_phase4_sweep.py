"""Part 2 deterministic full-sweep runner for ALTCOIN_MULTITF_005.

Extends the Part 1 contract with immutable-input verification, a dataset-backed
parallel evaluation of all 5,832 frozen configurations and atomic resumable
checkpoints guarded by config/input/protocol hashes. The frozen engine, grid,
costs, seeds and gates are consumed exactly as defined; nothing is weakened.
The evaluation interval stays sealed: this module never touches evaluation data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

from research.altcoin_multitf_gates import ConfigMetrics, compute_metrics
from research.altcoin_multitf_inputs import (
    PRIMARY_ARCHIVE_SHA256,
    PRIMARY_ARCHIVE_SIZE,
    SUPPLEMENT_ARCHIVE_SHA256,
    SUPPLEMENT_ARCHIVE_SIZE,
    UNIVERSE_SYMBOLS,
    CompositeInputs,
    InputError,
    assert_development_path,
    composite_manifest,
    sha256_file,
    verify_archive,
    _safe_extract,
)
from research.altcoin_multitf_phase3 import StrategyConfig, write_json_atomic
from research.altcoin_multitf_phase4 import Evaluation, FundingEvent
from research.altcoin_multitf_phase4_fast import CompactSeries, IndicatorCache, evaluate_compact
from research.altcoin_multitf_phase4_runner import EXPECTED_GRID_COUNT, SEED, deterministic_chunks, frozen_grid

PROTOCOL_DOC = Path("docs/ALTCOIN_MULTITF_FROZEN_PROTOCOL.md")
INITIAL_EQUITY_PER_SYMBOL = 10_000.0
CHUNK_SIZE = 243
SWEEP_SCHEMA = "altcoin-multitf-005-phase4-part2-sweep-v1"
SPA_REPLICATES = 1000
BOOTSTRAP_REPLICATES = 2000
SHORTLIST_SIZE = 25


class SweepError(RuntimeError):
    pass


def prepare_inputs(primary: Path, supplement: Path, inputs_root: Path, artifacts: Path, repo_commit: str) -> dict:
    primary_report = verify_archive(primary, PRIMARY_ARCHIVE_SHA256, PRIMARY_ARCHIVE_SIZE)
    supplement_report = verify_archive(supplement, SUPPLEMENT_ARCHIVE_SHA256, SUPPLEMENT_ARCHIVE_SIZE)
    merged = inputs_root / "merged"
    _safe_extract(primary, merged)
    _safe_extract(supplement, merged)
    tree_records = []
    for path in sorted(p for p in merged.rglob("*") if p.is_file()):
        assert_development_path(path)
        tree_records.append({"path": str(path.relative_to(merged)).replace("\\", "/"), "size": path.stat().st_size, "sha256": sha256_file(path)})
    tree_digest = hashlib.sha256(json.dumps(tree_records, sort_keys=True).encode()).hexdigest()
    manifest = composite_manifest(PROTOCOL_DOC, repo_commit, primary, supplement, True)
    manifest["merged_tree_file_count"] = len(tree_records)
    manifest["merged_tree_digest"] = tree_digest
    artifacts.mkdir(parents=True, exist_ok=True)
    write_json_atomic(artifacts / "input-manifest.json", manifest)
    write_json_atomic(inputs_root / "input-verification.json", {"archives": [primary_report, supplement_report], "tree_files": tree_records, "tree_digest": tree_digest})
    return {"primary": primary_report, "supplement": supplement_report, "merged_tree_digest": tree_digest, "files": len(tree_records)}


_WORKER: dict[str, Any] = {}


def _load_symbol_dataset(inputs: CompositeInputs, symbol: str) -> dict:
    execution = inputs.load_compact_series(symbol, 5)
    signals = {tf: inputs.load_compact_series(symbol, tf) for tf in (15, 60)}
    regime = inputs.load_compact_series(symbol, 240)
    funding = inputs.load_funding(symbol)
    rules = inputs.rules[symbol]
    return {"execution": execution, "signals": signals, "regime": regime, "funding": funding, "rules": rules}


def init_worker(inputs_root: str) -> None:
    from research.altcoin_multitf_phase4_fast import validate_compact

    merged = Path(inputs_root) / "merged"
    rules = CompositeInputs.load_rules(merged)
    inputs = CompositeInputs(merged, rules)
    datasets = {}
    entries: dict[str, dict[int, tuple[dict, dict]]] = {}
    for symbol in UNIVERSE_SYMBOLS:
        dataset = _load_symbol_dataset(inputs, symbol)
        for series in (dataset["execution"], dataset["regime"], *dataset["signals"].values()):
            if not len(series):
                raise SweepError(f"empty series for {symbol}")
            try:
                validate_compact(series)
            except ValueError as exc:
                raise SweepError(f"invalid series for {symbol}: {exc}") from exc
        datasets[symbol] = dataset
        builder = IndicatorCache(max_entries=64)
        sig15 = builder.signal_entry(id(dataset["signals"][15]), dataset["signals"][15])
        reg = builder.regime_entry(id(dataset["regime"]), dataset["regime"])
        sig60 = builder.signal_entry(id(dataset["signals"][60]), dataset["signals"][60])
        entries[symbol] = {15: (sig15, reg), 60: (sig60, reg)}
    _WORKER["datasets"] = datasets
    _WORKER["entries"] = entries
    _WORKER["cache"] = IndicatorCache(max_entries=64)


def row_from_metrics(metrics: ConfigMetrics, config: StrategyConfig) -> dict[str, object]:
    denominator = INITIAL_EQUITY_PER_SYMBOL * len(UNIVERSE_SYMBOLS)
    return {
        "key": metrics.config_key,
        "family": config.family.value,
        "signal_tf_minutes": config.signal_tf_minutes,
        "fast_window": config.fast_window,
        "slow_window": config.slow_window,
        "entry_threshold": config.entry_threshold,
        "exit_threshold": config.exit_threshold,
        "stop_atr": config.stop_atr,
        "take_atr": config.take_atr,
        "max_holding_bars": config.max_holding_bars,
        "valid": metrics.valid,
        "zero_trade": metrics.zero_trade,
        "invalid_reason": metrics.invalid_reason,
        "trades": metrics.trades,
        "net_pnl": metrics.net_pnl,
        "net_return": metrics.net_pnl / denominator,
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


def evaluate_config_row(config: StrategyConfig) -> dict[str, object]:
    datasets = _WORKER["datasets"]
    entries = _WORKER["entries"]
    cache: IndicatorCache = _WORKER["cache"]
    evaluations: dict[str, Evaluation] = {}
    tf = config.signal_tf_minutes
    for symbol in sorted(datasets):
        dataset = datasets[symbol]
        sig_entry, reg_entry = entries[symbol][tf]
        evaluations[symbol] = evaluate_compact(
            config,
            dataset["execution"],
            dataset["signals"][tf],
            dataset["regime"],
            dataset["funding"],
            dataset["rules"],
            prevalidated=True,
            cache=cache,
            symbol=symbol,
            signal_tf=tf,
            signal_entry=sig_entry,
            regime_entry=reg_entry,
        )
    metrics = compute_metrics(config.key, evaluations, initial_equity=INITIAL_EQUITY_PER_SYMBOL)
    return row_from_metrics(metrics, config)


def evaluate_chunk(chunk_index: int) -> dict[str, object]:
    grid = sorted(frozen_grid(), key=lambda item: item.key)
    chunks = deterministic_chunks(grid, CHUNK_SIZE)
    rows = [evaluate_config_row(config) for config in chunks[chunk_index]]
    return {"chunk_index": chunk_index, "rows": rows}


def sweep_context_hash(artifacts: Path) -> str:
    manifest_path = artifacts / "input-manifest.json"
    if not manifest_path.is_file():
        raise SweepError("input-manifest.json missing; run --prepare-inputs first")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "primary_sha256": payload["primary_archive"]["sha256"],
        "supplement_sha256": payload["supplement_archive"]["sha256"],
        "protocol_sha256": payload["frozen_protocol_sha256"],
        "merged_tree_digest": payload.get("merged_tree_digest"),
    }
    if required["primary_sha256"] != PRIMARY_ARCHIVE_SHA256 or required["supplement_sha256"] != SUPPLEMENT_ARCHIVE_SHA256:
        raise SweepError("input-manifest archive hashes do not match the frozen inputs")
    return hashlib.sha256(json.dumps(required, sort_keys=True).encode()).hexdigest()


def load_checkpoint(cache_dir: Path, context_hash: str) -> dict:
    path = cache_dir / "checkpoint.json"
    if not path.is_file():
        return new_checkpoint(context_hash)
    payload = json.loads(path.read_text(encoding="utf-8"))
    guards = (
        ("schema", SWEEP_SCHEMA),
        ("seed", SEED),
        ("grid_count", EXPECTED_GRID_COUNT),
        ("context_hash", context_hash),
    )
    for name, expected in guards:
        if payload.get(name) != expected:
            raise SweepError(f"resume rejected: checkpoint {name} mismatch ({payload.get(name)!r} != {expected!r}); refusing to mix runs")
    return payload


def new_checkpoint(context_hash: str) -> dict:
    return {"schema": SWEEP_SCHEMA, "seed": SEED, "grid_count": EXPECTED_GRID_COUNT, "context_hash": context_hash, "completed_keys": []}


def save_checkpoint(cache_dir: Path, state: dict) -> None:
    write_json_atomic(cache_dir / "checkpoint.json", state)


def chunk_keys(chunk_index: int) -> list[str]:
    grid = sorted(frozen_grid(), key=lambda item: item.key)
    chunks = deterministic_chunks(grid, CHUNK_SIZE)
    return [config.key for config in chunks[chunk_index]]


def total_chunks() -> int:
    grid = sorted(frozen_grid(), key=lambda item: item.key)
    return len(deterministic_chunks(grid, CHUNK_SIZE))


def execute_sweep(inputs_root: Path, artifacts: Path, cache_dir: Path, workers: int) -> dict:
    import multiprocessing as mp

    context_hash = sweep_context_hash(artifacts)
    grid = frozen_grid()
    if len(grid) != EXPECTED_GRID_COUNT:
        raise SweepError(f"frozen grid mismatch: {len(grid)} != {EXPECTED_GRID_COUNT}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    state = load_checkpoint(cache_dir, context_hash)
    completed: set[str] = set(state["completed_keys"])
    started = time.time()
    pending = [
        index
        for index in range(total_chunks())
        if not all(key in completed for key in chunk_keys(index))
    ]
    print(f"sweep start: pending_chunks={len(pending)} workers={workers}", flush=True)
    if pending:
        with mp.Pool(processes=workers, initializer=init_worker, initargs=(str(inputs_root),)) as pool:
            for done_index, result in ((item["chunk_index"], item) for item in pool.imap_unordered(evaluate_chunk, pending)):
                write_json_atomic(cache_dir / f"chunk-{done_index:04d}.json", result["rows"])
                completed.update(row["key"] for row in result["rows"])
                state["completed_keys"] = sorted(completed)
                save_checkpoint(cache_dir, state)
                print(f"chunk {done_index} done; completed={len(completed)}/{len(grid)} elapsed={time.time()-started:.0f}s", flush=True)
    else:
        print("no pending chunks; checkpoint complete", flush=True)
    marker = {
        "seed": SEED,
        "expected": len(grid),
        "completed": len(completed),
        "complete": len(completed) == len(grid),
        "elapsed_seconds": time.time() - started,
    }
    write_json_atomic(cache_dir / "completion.json", marker)
    if not marker["complete"]:
        raise SweepError("sweep incomplete after execution")
    state["completed_keys"] = sorted(completed)
    save_checkpoint(cache_dir, state)
    return marker


def load_all_rows(cache_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(cache_dir.glob("chunk-*.json")):
        rows.extend(json.loads(path.read_text(encoding="utf-8")))
    keys = [row["key"] for row in rows]
    if len(keys) != len(set(keys)):
        raise SweepError("duplicate configuration keys across chunks")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-grid", action="store_true")
    parser.add_argument("--prepare-inputs", action="store_true")
    parser.add_argument("--full-sweep", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--primary", type=Path, default=None)
    parser.add_argument("--supplement", type=Path, default=None)
    parser.add_argument("--inputs-root", type=Path, default=None)
    parser.add_argument("--artifacts", type=Path, default=Path("reports/artifacts/altcoin-multitf-005-phase4"))
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=0)
    args = parser.parse_args(argv)

    import subprocess

    if args.validate_grid:
        grid = frozen_grid()
        summary = {"count": len(grid), "first_key": sorted(c.key for c in grid)[0], "seed": SEED}
        if len(grid) != EXPECTED_GRID_COUNT:
            print(json.dumps({"error": "grid mismatch", **summary}, sort_keys=True))
            return 1
        print(json.dumps(summary, sort_keys=True))
        return 0
    if args.prepare_inputs:
        missing = [name for name in ("primary", "supplement", "inputs_root") if getattr(args, name) is None]
        if missing:
            parser.error(f"--prepare-inputs requires --{missing[0].replace('_', '-')}")
        repo_commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        report = prepare_inputs(args.primary, args.supplement, args.inputs_root, args.artifacts, repo_commit)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.full_sweep:
        if args.inputs_root is None:
            parser.error("--full-sweep requires --inputs-root")
        cache_dir = args.cache_dir or (args.inputs_root.parent / "phase4-sweep-cache")
        workers = args.workers or max(1, (platform.cpu_count() or 2) - 2)
        marker = execute_sweep(args.inputs_root, args.artifacts, cache_dir, workers)
        print(json.dumps(marker, sort_keys=True))
        return 0
    if args.finalize:
        if args.inputs_root is None:
            parser.error("--finalize requires --inputs-root")
        cache_dir = args.cache_dir or (args.inputs_root.parent / "phase4-sweep-cache")
        from research.altcoin_multitf_phase4_finalize import finalize_selection

        outcome = finalize_selection(args.artifacts, cache_dir, args.inputs_root)
        print(json.dumps(outcome, sort_keys=True))
        return 0
    parser.error("select a stage: --validate-grid | --prepare-inputs | --full-sweep | --finalize")
    return 2


if __name__ == "__main__":
    sys.exit(main())
