from __future__ import annotations

import argparse
import json
import os
import platform
import random
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .core import CostModel
from .data import download_symbol
from .features import make_features
from .phase1_audit import CANDIDATE, r_metrics
from .search import Calibration, evaluate_candidate

ROOT = Path(__file__).resolve().parents[1]
FROZEN_SHA = "81f5ea590edbc04fadce762452801c1d365470d0"
TEST_START_TS = 1_735_689_600_000
TEST_END_TS = 1_767_225_600_000
APPROVAL_PHRASE = f"I AUTHORIZE THE ONE-TIME TEST OPENING FOR {FROZEN_SHA}"
MANIFEST = ROOT / "docs" / "test-opening-hashes.json"
MEMO = ROOT / "docs" / "TEST_OPENING_MEMO.md"
AUDIT_DIR = ROOT / "reports" / "private" / "test-opening"
SENTINEL = AUDIT_DIR / "OPENED_ONCE.json"
RESULT = AUDIT_DIR / "result.json"
BOOTSTRAP_SEED = 6996
BOOTSTRAP_RESAMPLES = 100_000
BASE_COST = CostModel(taker_fee_bps=5, half_spread_bps=0, slippage_bps=0)
FROZEN_CALIBRATION = Calibration(threshold=0.011212442111818932, rv_median=0.031884225572892805)


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def bootstrap_ci95(values: list[float]) -> list[float | None]:
    if not values:
        return [None, None]
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(values)
    means = [sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(BOOTSTRAP_RESAMPLES)]
    return [percentile(means, 0.025), percentile(means, 0.975)]


def _exclusive_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def verify_gate(approval: str, frozen_sha: str) -> None:
    from .test_opening_integrity import verify_all

    if frozen_sha != FROZEN_SHA:
        raise RuntimeError("full frozen SHA does not match")
    if approval != APPROVAL_PHRASE:
        raise RuntimeError("owner approval phrase does not match exactly")
    if SENTINEL.exists() or RESULT.exists():
        raise RuntimeError("TEST has already been opened or an opening was attempted")
    verify_all(require_source_cache=True)


def execute_once(approval: str, frozen_sha: str) -> dict:
    # All imports above are data-access free. Every fail-closed check finishes before this sentinel.
    verify_gate(approval, frozen_sha)
    opened_at = datetime.now(timezone.utc).isoformat()
    audit = {
        "status": "OPENING_IRREVERSIBLY",
        "opened_at": opened_at,
        "frozen_sha": FROZEN_SHA,
        "approval_phrase_matched": True,
        "argv": ["python3", "-m", "research.test_opening", "--frozen-sha", FROZEN_SHA, "--approve", APPROVAL_PHRASE],
    }
    _exclusive_json(SENTINEL, audit)  # Deliberately before the first TEST byte is requested.

    btc, _, btc_manifest = download_symbol("BTCUSDT", 2021, 2025, ROOT / "data", interval="1h")
    eth, funding, eth_manifest = download_symbol("ETHUSDT", 2021, 2025, ROOT / "data", interval="1h")
    if [bar.ts for bar in btc] != [bar.ts for bar in eth]:
        raise RuntimeError("BTC and ETH timelines do not align")
    features = make_features(eth, funding, btc)
    test_indices = [i for i, bar in enumerate(eth) if TEST_START_TS <= bar.ts < TEST_END_TS]
    if not test_indices or eth[test_indices[0]].ts != TEST_START_TS:
        raise RuntimeError("TEST must begin exactly at 2025-01-01 00:00:00 UTC")
    trades, _ = evaluate_candidate(CANDIDATE, eth, features, test_indices, BASE_COST, dict(funding), FROZEN_CALIBRATION)
    rows, diagnostics = r_metrics(trades, eth, features)
    values = [float(row["result_r"]) for row in rows]
    ci95 = bootstrap_ci95(values)
    expectancy_r = sum(values) / len(values) if values else None
    passed = len(values) >= 30 and ci95[0] is not None and ci95[0] > 0
    result = {
        "verdict": "PASS" if passed else "FAIL",
        "primary": {
            "metric": "mean_expectancy_R",
            "value": expectancy_r,
            "ci95": ci95,
            "minimum_trades": 30,
            "criterion": "trade_count >= 30 AND ci95_lower > 0",
            "bootstrap": {"method": "iid trade resampling with replacement; percentile interval", "seed": BOOTSTRAP_SEED, "resamples": BOOTSTRAP_RESAMPLES, "quantiles": [0.025, 0.975]},
        },
        "secondary_diagnostics_verdict_neutral": {**diagnostics, "trade_count": len(values)},
        "audit": {
            **audit,
            "status": "COMPLETED",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "governance_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "manifest_sha256": __import__("hashlib").sha256(MANIFEST.read_bytes()).hexdigest(),
            "python": sys.version,
            "platform": platform.platform(),
            "source_quality": {"BTCUSDT": btc_manifest["quality"], "ETHUSDT": eth_manifest["quality"]},
        },
    }
    _exclusive_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Irreversible one-time frozen TEST opening")
    parser.add_argument("--frozen-sha", required=True)
    parser.add_argument("--approve", required=True)
    args = parser.parse_args()
    result = execute_once(args.approve, args.frozen_sha)
    print(json.dumps({"verdict": result["verdict"], "primary": result["primary"]}, indent=2))


if __name__ == "__main__":
    main()
