"""Deterministic, resumable Phase 4 runner contract.

Part 1 supports grid validation, dry runs and chunk/checkpoint mechanics. Part 2 must
provide immutable datasets and explicitly opt into a full sweep.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from itertools import product
import json
import platform
from pathlib import Path
import random
import sys
from typing import Callable, Iterable

from research.altcoin_multitf_phase3 import Family, StrategyConfig, write_json_atomic

SEED = 20250304
EXPECTED_GRID_COUNT = 5_832


def frozen_grid() -> tuple[StrategyConfig, ...]:
    axes = product(
        (Family.A, Family.B),
        (15, 60),
        (240,),
        (3, 5, 8),
        (13, 21, 34),
        (0.0, 0.005, 0.01),
        (0.0, 0.003),
        (1.5, 2.0, 2.5),
        (2.0, 3.0, 4.0),
        (12, 24, 48),
    )
    result = tuple(StrategyConfig(*values) for values in axes if values[3] < values[4])
    if len(result) != EXPECTED_GRID_COUNT:
        raise RuntimeError(f"frozen grid mismatch: {len(result)} != {EXPECTED_GRID_COUNT}")
    if len({item.key for item in result}) != len(result):
        raise RuntimeError("configuration key collision")
    return result


def deterministic_chunks(items: Iterable[StrategyConfig], chunk_size: int) -> tuple[tuple[StrategyConfig, ...], ...]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    ordered = sorted(items, key=lambda item: item.key)
    return tuple(tuple(ordered[i : i + chunk_size]) for i in range(0, len(ordered), chunk_size))


def run_chunks(
    configs: Iterable[StrategyConfig],
    output: Path,
    evaluator: Callable[[StrategyConfig], dict[str, object]],
    *,
    chunk_size: int = 250,
) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    completed: set[str] = set()
    checkpoint = output / "checkpoint.json"
    if checkpoint.exists():
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        if payload.get("seed") != SEED:
            raise RuntimeError("checkpoint seed mismatch")
        completed = set(payload.get("completed_keys", []))
    all_configs = sorted(configs, key=lambda item: item.key)
    for index, chunk in enumerate(deterministic_chunks(all_configs, chunk_size)):
        pending = [config for config in chunk if config.key not in completed]
        rows = [evaluator(config) for config in pending]
        if rows:
            write_json_atomic(output / f"chunk-{index:05d}.json", rows)
            completed.update(config.key for config in pending)
            write_json_atomic(checkpoint, {"seed": SEED, "completed_keys": sorted(completed)})
    marker = {"seed": SEED, "expected": len(all_configs), "completed": len(completed), "complete": len(completed) == len(all_configs)}
    write_json_atomic(output / "completion.json", marker)
    return marker


def manifest() -> dict[str, object]:
    return {
        "seed": SEED,
        "expected_grid_count": EXPECTED_GRID_COUNT,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "grid": [{**asdict(config), "family": config.family.value, "key": config.key} for config in frozen_grid()],
        "input_hashes": {},
        "status": "PART1_GRID_ONLY",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-grid", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("reports/artifacts/altcoin-multitf-005-phase4"))
    args = parser.parse_args(argv)
    random.seed(SEED)
    grid = frozen_grid()
    if not (args.validate_grid or args.dry_run):
        parser.error("Part 1 permits only --validate-grid or --dry-run; Part 2 owns the full sweep")
    summary = {"count": len(grid), "first_key": sorted(c.key for c in grid)[0], "seed": SEED}
    if args.dry_run:
        write_json_atomic(args.output / "run-manifest.part1.json", manifest())
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
