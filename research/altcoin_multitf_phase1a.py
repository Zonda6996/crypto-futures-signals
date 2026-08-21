from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PROTOCOL_ID = "ALT-MULTITF-003"
DEVELOPMENT_START_MS = 1_567_900_800_000  # 2019-09-08T00:00:00Z
HOLDOUT_START_MS = 1_767_225_600_000  # 2026-01-01T00:00:00Z
HOLDOUT_END_MS = 1_785_542_400_000  # 2026-08-01T00:00:00Z
RAW_ROOT_NAME = "altcoin-multitf-003"
DEVELOPMENT_DIR = "development"
SEALED_DIR = "sealed-holdout"


class LifecycleGateError(RuntimeError):
    pass


class SealedPayloadAccessError(PermissionError):
    pass


@dataclass(frozen=True)
class LifecycleRecord:
    symbol: str
    pair: str
    base_asset: str
    quote_asset: str
    margin_asset: str
    contract_type: str
    onboard_ms: int | None
    delivery_ms: int | None
    status: str
    source_url: str
    source_sha256: str
    acquired_at: str
    historical_terminal_evidence: str | None = None


@dataclass(frozen=True)
class RawFileRecord:
    path: str
    size: int
    sha256: str
    source: str
    symbol: str
    datatype: str
    timeframe: str | None
    start_ms: int
    end_exclusive_ms: int
    acquisition_timestamp: str
    partition: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def lifecycle_gate_issues(records: Iterable[LifecycleRecord], *, source_set_complete: bool) -> list[str]:
    rows = list(records)
    issues: list[str] = []
    if not source_set_complete:
        issues.append("official source set does not prove exhaustive historical contract discovery")
    if not rows:
        issues.append("lifecycle registry is empty")
        return issues
    seen: set[tuple[str, int | None]] = set()
    for row in rows:
        key = (row.symbol, row.onboard_ms)
        if key in seen:
            issues.append(f"duplicate lifecycle: {row.symbol}/{row.onboard_ms}")
        seen.add(key)
        if row.contract_type != "PERPETUAL" or row.quote_asset != "USDT" or row.margin_asset != "USDT":
            issues.append(f"out-of-scope contract: {row.symbol}")
        if row.onboard_ms is None:
            issues.append(f"missing authoritative onboard time: {row.symbol}")
        if not row.source_url.startswith("https://") or len(row.source_sha256) != 64:
            issues.append(f"invalid provenance: {row.symbol}")
        if row.delivery_ms is not None and row.onboard_ms is not None and row.delivery_ms <= row.onboard_ms:
            issues.append(f"invalid lifecycle bounds: {row.symbol}")
        if row.status != "TRADING" and row.delivery_ms is None:
            issues.append(f"terminal contract missing authoritative delist time: {row.symbol}")
    if not any(row.status != "TRADING" for row in rows):
        issues.append("registry has no delisted/expired/failed contract evidence")
    return issues


def require_lifecycle_gate(records: Iterable[LifecycleRecord], *, source_set_complete: bool) -> None:
    issues = lifecycle_gate_issues(records, source_set_complete=source_set_complete)
    if issues:
        raise LifecycleGateError("; ".join(issues))


def classify_partition(start_ms: int, end_exclusive_ms: int) -> str:
    if start_ms >= end_exclusive_ms:
        raise ValueError("empty or reversed interval")
    if DEVELOPMENT_START_MS <= start_ms and end_exclusive_ms <= HOLDOUT_START_MS:
        return DEVELOPMENT_DIR
    if HOLDOUT_START_MS <= start_ms and end_exclusive_ms <= HOLDOUT_END_MS:
        return SEALED_DIR
    raise ValueError("interval crosses or exceeds frozen partition boundaries")


def safe_target(root: Path, partition: str, relative_path: Path) -> Path:
    if partition not in {DEVELOPMENT_DIR, SEALED_DIR}:
        raise ValueError("unknown raw partition")
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("unsafe relative path")
    base = (root / RAW_ROOT_NAME / partition).resolve()
    target = (base / relative_path).resolve()
    if target != base and base not in target.parents:
        raise ValueError("target escapes raw partition")
    return target


def atomic_store_raw(
    root: Path,
    relative_path: Path,
    payload: bytes,
    *,
    source: str,
    symbol: str,
    datatype: str,
    timeframe: str | None,
    start_ms: int,
    end_exclusive_ms: int,
    acquired_at: str | None = None,
) -> RawFileRecord:
    partition = classify_partition(start_ms, end_exclusive_ms)
    target = safe_target(root, partition, relative_path)
    digest = sha256_bytes(payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.stat().st_size != len(payload) or _sha256_file(target) != digest:
            raise FileExistsError(f"resume checksum conflict: {target}")
    else:
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".part", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return RawFileRecord(
        path=str(target.relative_to(root)), size=len(payload), sha256=digest, source=source,
        symbol=symbol, datatype=datatype, timeframe=timeframe, start_ms=start_ms,
        end_exclusive_ms=end_exclusive_ms, acquisition_timestamp=acquired_at or utc_now(), partition=partition,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(records: Iterable[RawFileRecord]) -> list[str]:
    rows = list(records)
    issues: list[str] = []
    paths: set[str] = set()
    logical: set[tuple[str, str, str | None, int, int]] = set()
    for row in rows:
        if row.path in paths:
            issues.append(f"duplicate path: {row.path}")
        paths.add(row.path)
        key = (row.symbol, row.datatype, row.timeframe, row.start_ms, row.end_exclusive_ms)
        if key in logical:
            issues.append(f"duplicate logical file: {key}")
        logical.add(key)
        try:
            expected = classify_partition(row.start_ms, row.end_exclusive_ms)
        except ValueError as error:
            issues.append(f"invalid boundary {row.path}: {error}")
            continue
        if row.partition != expected or f"/{expected}/" not in f"/{row.path}":
            issues.append(f"partition mismatch: {row.path}")
        if row.size < 0 or len(row.sha256) != 64:
            issues.append(f"invalid inventory fields: {row.path}")
    return issues


def write_manifest(path: Path, records: Iterable[RawFileRecord]) -> str:
    rows = sorted((asdict(row) for row in records), key=lambda row: row["path"])
    payload = (json.dumps({"protocol_id": PROTOCOL_ID, "files": rows}, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256_bytes(payload)


def research_read(path: Path, *, raw_root: Path) -> bytes:
    sealed = (raw_root / RAW_ROOT_NAME / SEALED_DIR).resolve()
    resolved = path.resolve()
    if resolved == sealed or sealed in resolved.parents:
        raise SealedPayloadAccessError("research code cannot read sealed holdout payload")
    return path.read_bytes()
