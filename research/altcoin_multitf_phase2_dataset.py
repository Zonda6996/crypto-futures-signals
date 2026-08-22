from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from research.altcoin_multitf_phase2 import (
    Bar,
    EligibilityRun,
    FROZEN_PARAMETERS,
    FundingRecord,
    generate_signals,
)

PROTOCOL_ID = "ALT-MULTITF-005"
ENGINE_SPEC_ID = "ALT-MULTITF-005-PHASE2-FROZEN-1"
TIMEFRAME_MS = {
    "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "1d": 86_400_000,
}
KLINE_HEADER = ["open_time_ms", "open", "high", "low", "close", "volume", "close_time_ms", "quote_volume", "trade_count", "taker_buy_base", "taker_buy_quote"]
FUNDING_HEADER = ["funding_time_ms", "funding_rate", "mark_price"]


@dataclass(frozen=True)
class DevelopmentSlice:
    protocol_id: str
    manifest_sha256: str
    roster: tuple[str, ...]
    bars_by_symbol: dict[str, tuple[Bar, ...]]
    funding: tuple[FundingRecord, ...]
    eligibility: tuple[EligibilityRun, ...]


def _reject_holdout(*values: object) -> None:
    if any("holdout" in str(value).lower() for value in values):
        raise ValueError("holdout access is forbidden")


def _read_json(path: Path) -> object:
    _reject_holdout(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _group(timeframe: str) -> str:
    if timeframe in {"5m", "15m", "30m"}: return "short"
    if timeframe in {"1h", "2h", "4h"}: return "medium"
    if timeframe == "1d": return "long"
    raise ValueError(f"unsupported timeframe: {timeframe}")


def load_development_slice(dataset: Path | str, timeframe: str, decision_time_ms: int) -> DevelopmentSlice:
    _reject_holdout(dataset, timeframe)
    base = Path(dataset)
    if timeframe not in TIMEFRAME_MS or decision_time_ms < 0:
        raise ValueError("invalid timeframe or decision timestamp")
    manifest_path = base / "metadata" / "normalized-development-manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("protocol_id") != PROTOCOL_ID or manifest.get("partition") != "development":
        raise ValueError("not the ALT-MULTITF-005 development dataset")
    roster_doc = _read_json(base / "metadata" / "roster.snapshot.json")
    if roster_doc.get("protocol_id") != PROTOCOL_ID or roster_doc.get("symbol_count") != 40:
        raise ValueError("invalid frozen roster metadata")
    roster = tuple(roster_doc["symbols"])
    if len(roster) != 40 or len(set(roster)) != 40 or "BTWUSDT" not in roster:
        raise ValueError("invalid frozen roster")
    eligibility_doc = _read_json(base / "development" / "audit" / "eligibility.json")
    if eligibility_doc.get("protocol_id") != PROTOCOL_ID:
        raise ValueError("invalid eligibility artifact")
    eligibility = tuple(EligibilityRun(str(r["symbol"]), int(r["start_ms"]), int(r["end_exclusive_ms"]), str(r["state"])) for r in eligibility_doc["runs"])
    limit = max(vars(FROZEN_PARAMETERS[_group(timeframe)]).values()) + 1
    bars_by_symbol: dict[str, tuple[Bar, ...]] = {}
    funding: list[FundingRecord] = []
    step = TIMEFRAME_MS[timeframe]
    for symbol in roster:
        path = base / "development" / "normalized" / "klines" / symbol / f"{symbol}-{timeframe}.csv.gz"
        _reject_holdout(path)
        kept: deque[Bar] = deque(maxlen=limit)
        if path.exists():
            previous = -1
            with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                if next(reader, None) != KLINE_HEADER: raise ValueError(f"invalid kline schema: {symbol}")
                for row in reader:
                    if len(row) != len(KLINE_HEADER): raise ValueError(f"invalid kline row: {symbol}")
                    opened, closed, close = int(row[0]), int(row[6]), float(row[4])
                    if opened <= previous or closed != opened + step - 1: raise ValueError(f"invalid kline timestamps: {symbol}")
                    previous = opened
                    if not math.isfinite(close) or close <= 0: raise ValueError(f"invalid close: {symbol}")
                    if closed <= decision_time_ms: kept.append(Bar(symbol, timeframe, opened, closed, close))
                    elif opened > decision_time_ms: break
        bars_by_symbol[symbol] = tuple(kept)
        funding_path = base / "development" / "normalized" / "funding" / symbol / f"{symbol}-funding.csv.gz"
        _reject_holdout(funding_path)
        if funding_path.exists():
            recent: deque[FundingRecord] = deque(maxlen=FROZEN_PARAMETERS[_group(timeframe)].funding_bars)
            previous = -1
            with gzip.open(funding_path, "rt", encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                if next(reader, None) != FUNDING_HEADER: raise ValueError(f"invalid funding schema: {symbol}")
                for row in reader:
                    published, rate = int(row[0]), float(row[1])
                    if published <= previous or not math.isfinite(rate): raise ValueError(f"invalid funding row: {symbol}")
                    previous = published
                    if published <= decision_time_ms: recent.append(FundingRecord(symbol, published, rate))
                    else: break
            funding.extend(recent)
    return DevelopmentSlice(PROTOCOL_ID, hashlib.sha256(manifest_bytes).hexdigest(), roster, bars_by_symbol, tuple(funding), eligibility)


def run_integration(dataset: Path | str) -> dict:
    # Mechanical choices: the UTC day boundary before dataset end, and end_exclusive - 1.
    checks = (("5m", 1767139200000), ("5m", 1767225599999), ("1h", 1767139200000), ("1h", 1767225599999), ("1d", 1767139200000), ("1d", 1767225599999))
    records = []
    manifest_sha = None
    digest_rows = []
    for timeframe, decision in checks:
        loaded = load_development_slice(dataset, timeframe, decision)
        manifest_sha = loaded.manifest_sha256
        rows, diagnostics = generate_signals(decision_time_ms=decision, timeframe=timeframe, bars_by_symbol=loaded.bars_by_symbol, funding=loaded.funding, eligibility=loaded.eligibility)
        record = {"timeframe": timeframe, "decision_time_ms": decision, **asdict(diagnostics)}
        record["excluded_symbols"] = list(record["excluded_symbols"])
        records.append(record)
        digest_rows.extend(asdict(row) for row in rows)
    encoded = json.dumps(digest_rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"protocol_id": PROTOCOL_ID, "input_manifest_sha256": manifest_sha, "engine_spec_id": ENGINE_SPEC_ID, "checks": records, "deterministic_output_sha256": hashlib.sha256(encoded).hexdigest(), "prohibited_fields_absent": True}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact = run_integration(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(artifact, sort_keys=True))


if __name__ == "__main__": main()
