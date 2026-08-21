from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

PROTOCOL_ID = "ALT-MULTITF-003"
DEVELOPMENT_START_MS = 1_567_900_800_000
HOLDOUT_START_MS = 1_767_225_600_000
HOLDOUT_END_MS = 1_785_542_400_000
RAW_ROOT_NAME = "altcoin-multitf-003"
DEVELOPMENT_DIR = "development"
SEALED_DIR = "sealed-holdout"
OFFICIAL_EXCHANGE_INFO_URLS = (
    "https://fapi.binance.com/fapi/v1/exchangeInfo",
    "https://fapi1.binance.com/fapi/v1/exchangeInfo",
    "https://fapi2.binance.com/fapi/v1/exchangeInfo",
    "https://fapi3.binance.com/fapi/v1/exchangeInfo",
    "https://fapi4.binance.com/fapi/v1/exchangeInfo",
)


class RosterGateError(RuntimeError):
    pass


class SealedPayloadAccessError(PermissionError):
    pass


@dataclass(frozen=True)
class RosterRecord:
    symbol: str
    pair: str
    base_asset: str
    quote_asset: str
    margin_asset: str
    contract_type: str
    status: str
    onboard_ms: int | None
    delivery_ms: int | None


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def freeze_current_roster(payload: bytes, *, source_url: str, acquired_at: str) -> tuple[list[RosterRecord], dict]:
    """Validate official exchangeInfo bytes and derive the immutable A1 roster.

    This must run before any market-data request. Coverage must never be used to
    add or remove symbols from the returned roster.
    """
    if source_url not in OFFICIAL_EXCHANGE_INFO_URLS:
        raise RosterGateError("roster source is not an approved official Binance USD-M endpoint")
    if not payload:
        raise RosterGateError("official current roster response is empty")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RosterGateError("official current roster response is not valid JSON") from error
    symbols = document.get("symbols")
    if not isinstance(symbols, list):
        raise RosterGateError("official current roster response has no symbols array")
    rows: list[RosterRecord] = []
    for item in symbols:
        if not isinstance(item, dict):
            continue
        if (
            item.get("contractType") == "PERPETUAL"
            and item.get("quoteAsset") == "USDT"
            and item.get("marginAsset") == "USDT"
            and item.get("status") == "TRADING"
        ):
            rows.append(RosterRecord(
                symbol=str(item["symbol"]), pair=str(item.get("pair", item["symbol"])),
                base_asset=str(item["baseAsset"]), quote_asset="USDT", margin_asset="USDT",
                contract_type="PERPETUAL", status="TRADING", onboard_ms=item.get("onboardDate"),
                delivery_ms=item.get("deliveryDate"),
            ))
    rows.sort(key=lambda row: row.symbol)
    if not rows:
        raise RosterGateError("official current roster contains no in-scope trading contracts")
    names = [row.symbol for row in rows]
    if len(names) != len(set(names)):
        raise RosterGateError("official current roster contains duplicate symbols")
    snapshot = {
        "protocol_id": PROTOCOL_ID,
        "owner_amendment": "A1",
        "source_url": source_url,
        "acquisition_timestamp": acquired_at,
        "raw_size": len(payload),
        "raw_sha256": sha256_bytes(payload),
        "selection": "TRADING PERPETUAL quoteAsset=USDT marginAsset=USDT",
        "symbol_count": len(rows),
        "symbols": [asdict(row) for row in rows],
    }
    return rows, snapshot


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


def atomic_store_raw(root: Path, relative_path: Path, payload: bytes, *, source: str, symbol: str,
                     datatype: str, timeframe: str | None, start_ms: int, end_exclusive_ms: int,
                     acquired_at: str | None = None) -> RawFileRecord:
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
                handle.write(payload); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return RawFileRecord(str(target.relative_to(root)), len(payload), digest, source, symbol, datatype,
                         timeframe, start_ms, end_exclusive_ms, acquired_at or utc_now(), partition)


def validate_manifest(records: Iterable[RawFileRecord], *, root: Path | None = None) -> list[str]:
    rows = list(records); issues: list[str] = []; paths: set[str] = set(); logical: set[tuple] = set()
    for row in rows:
        if row.path in paths: issues.append(f"duplicate path: {row.path}")
        paths.add(row.path)
        key = (row.symbol, row.datatype, row.timeframe, row.start_ms, row.end_exclusive_ms)
        if key in logical: issues.append(f"duplicate logical file: {key}")
        logical.add(key)
        try: expected = classify_partition(row.start_ms, row.end_exclusive_ms)
        except ValueError as error:
            issues.append(f"invalid boundary {row.path}: {error}"); continue
        if row.partition != expected or f"/{expected}/" not in f"/{row.path}":
            issues.append(f"partition mismatch: {row.path}")
        if row.size < 0 or len(row.sha256) != 64: issues.append(f"invalid inventory fields: {row.path}")
        if root is not None:
            path = root / row.path
            if not path.is_file(): issues.append(f"missing file: {row.path}")
            elif path.stat().st_size != row.size or _sha256_file(path) != row.sha256:
                issues.append(f"filesystem checksum mismatch: {row.path}")
    return issues


def write_manifest(path: Path, records: Sequence[RawFileRecord]) -> str:
    issues = validate_manifest(records)
    if issues: raise ValueError("; ".join(issues))
    payload = (json.dumps({"protocol_id": PROTOCOL_ID, "files": sorted((asdict(r) for r in records), key=lambda r: r["path"])}, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(payload)
    return sha256_bytes(payload)


def research_read(path: Path, *, raw_root: Path) -> bytes:
    sealed = (raw_root / RAW_ROOT_NAME / SEALED_DIR).resolve(); resolved = path.resolve()
    if resolved == sealed or sealed in resolved.parents:
        raise SealedPayloadAccessError("research code cannot read sealed holdout payload")
    return path.read_bytes()
