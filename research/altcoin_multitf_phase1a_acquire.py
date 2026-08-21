"""Acquire and seal raw Binance data for ALT-MULTITF-003 Phase 1A only."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from research.altcoin_multitf_phase1a import (
    DEVELOPMENT_START_MS,
    HOLDOUT_END_MS,
    HOLDOUT_START_MS,
    PROTOCOL_ID,
    RAW_ROOT_NAME,
    RawFileRecord,
    freeze_current_roster,
    sha256_bytes,
    utc_now,
    validate_manifest,
    write_manifest,
)

EXCHANGE_INFO_URL = "https://www.binance.com/fapi/v1/exchangeInfo"
VISION = "https://data.binance.vision"
BUCKET_LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
USER_AGENT = "ALT-MULTITF-003-phase1a/1.0"
DEV_START = datetime(2019, 9, 8, tzinfo=timezone.utc)
DEV_END = datetime(2026, 1, 1, tzinfo=timezone.utc)
HOLDOUT_END = datetime(2026, 8, 1, tzinfo=timezone.utc)
OBJECT_RE = re.compile(r"-(\d{4})-(\d{2})(?:-(\d{2}))?\.zip$")


def fetch(url: str, retries: int = 6) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read()
                if not body:
                    raise RuntimeError(f"empty response: {url}")
                return body
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise
            last = error
        except (urllib.error.URLError, TimeoutError, RuntimeError) as error:
            last = error
        time.sleep(min(30, 2**attempt))
    raise RuntimeError(f"download failed after {retries} attempts: {url}") from last


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = sha256_bytes(payload)
    if path.exists():
        if path.stat().st_size != len(payload) or file_sha256(path) != digest:
            raise FileExistsError(f"resume checksum conflict: {path}")
        return
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def list_keys(prefix: str) -> list[str]:
    keys: list[str] = []
    token: str | None = None
    while True:
        query = {"list-type": "2", "prefix": prefix}
        if token:
            query["continuation-token"] = token
        root = ElementTree.fromstring(fetch(f"{BUCKET_LIST}?{urllib.parse.urlencode(query)}"))
        namespace = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
        keys.extend(node.text or "" for node in root.findall("s3:Contents/s3:Key", namespace))
        truncated = (root.findtext("s3:IsTruncated", default="false", namespaces=namespace) == "true")
        if not truncated:
            return keys
        token = root.findtext("s3:NextContinuationToken", namespaces=namespace)
        if not token:
            raise RuntimeError(f"truncated S3 listing without continuation token: {prefix}")


def object_bounds(key: str) -> tuple[int, int]:
    match = OBJECT_RE.search(key)
    if not match:
        raise ValueError(f"unrecognized archive date: {key}")
    year, month = int(match.group(1)), int(match.group(2))
    day = int(match.group(3)) if match.group(3) else 1
    start = datetime(year, month, day, tzinfo=timezone.utc)
    if match.group(3):
        end = datetime.fromtimestamp(start.timestamp() + 86400, tz=timezone.utc)
    elif month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def planned_keys(symbol: str, datatype: str) -> list[tuple[str, str, int, int]]:
    monthly_kind = "klines" if datatype == "klines" else "fundingRate"
    suffix = f"/{symbol}/5m/" if datatype == "klines" else f"/{symbol}/"
    monthly = list_keys(f"data/futures/um/monthly/{monthly_kind}{suffix}")
    selected: list[tuple[str, str, int, int]] = []
    for key in monthly:
        if not key.endswith(".zip"):
            continue
        start, end = object_bounds(key)
        if start >= int(datetime(2019, 10, 1, tzinfo=timezone.utc).timestamp() * 1000) and end <= HOLDOUT_END_MS:
            partition = "development" if end <= HOLDOUT_START_MS else "sealed-holdout"
            selected.append((key, partition, start, end))
    if datatype == "klines":
        daily = list_keys(f"data/futures/um/daily/klines/{symbol}/5m/")
        for key in daily:
            if not key.endswith(".zip"):
                continue
            start, end = object_bounds(key)
            if DEVELOPMENT_START_MS <= start and end <= int(datetime(2019, 10, 1, tzinfo=timezone.utc).timestamp() * 1000):
                selected.append((key, "development", start, end))
    return sorted(selected)


def acquire_one(root: Path, symbol: str, datatype: str, item: tuple[str, str, int, int]) -> RawFileRecord:
    key, partition, start, end = item
    source = f"{VISION}/{key}"
    relative = Path(RAW_ROOT_NAME) / partition / datatype / symbol / Path(key).name
    target = root / relative
    acquired = utc_now()
    if target.exists():
        payload_size = target.stat().st_size
        digest = file_sha256(target)
    else:
        payload = fetch(source)
        atomic_bytes(target, payload)
        payload_size = len(payload)
        digest = sha256_bytes(payload)
    return RawFileRecord(
        path=str(relative), size=payload_size, sha256=digest, source=source, symbol=symbol,
        datatype=datatype, timeframe="5m" if datatype == "klines" else None,
        start_ms=start, end_exclusive_ms=end, acquisition_timestamp=acquired, partition=partition,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data"))
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    root: Path = args.root
    metadata = root / RAW_ROOT_NAME / "metadata"
    raw_path = metadata / "exchangeInfo.raw.json"
    snapshot_path = metadata / "roster.snapshot.json"
    if raw_path.exists() or snapshot_path.exists():
        if not (raw_path.exists() and snapshot_path.exists()):
            raise RuntimeError("incomplete immutable roster snapshot; manual audit required")
        raw_exchange = raw_path.read_bytes()
        frozen_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        roster, snapshot = freeze_current_roster(
            raw_exchange,
            source_url=str(frozen_snapshot["source_url"]),
            acquired_at=str(frozen_snapshot["acquisition_timestamp"]),
        )
        if snapshot != frozen_snapshot:
            raise RuntimeError("immutable roster snapshot validation mismatch")
    else:
        raw_exchange = fetch(EXCHANGE_INFO_URL)
        acquired = utc_now()
        roster, snapshot = freeze_current_roster(raw_exchange, source_url=EXCHANGE_INFO_URL, acquired_at=acquired)
        atomic_bytes(raw_path, raw_exchange)
        atomic_bytes(snapshot_path, (json.dumps(snapshot, indent=2, sort_keys=True) + "\n").encode())

    plan: list[tuple[str, str, tuple[str, str, int, int]]] = []
    def plan_symbol(symbol: str) -> list[tuple[str, str, tuple[str, str, int, int]]]:
        return [
            (symbol, datatype, item)
            for datatype in ("klines", "funding")
            for item in planned_keys(symbol, datatype)
        ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as planner:
        futures = {planner.submit(plan_symbol, row.symbol): row.symbol for row in roster}
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            plan.extend(future.result())
            if index % 25 == 0:
                print(f"planned {index}/{len(roster)} symbols: {len(plan)} files", flush=True)
    plan.sort(key=lambda row: (row[0], row[1], row[2][0]))
    atomic_bytes(metadata / "acquisition.plan.json", (json.dumps(plan, indent=2) + "\n").encode())

    records: list[RawFileRecord] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(acquire_one, root, symbol, datatype, item) for symbol, datatype, item in plan]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            records.append(future.result())
            if index % 100 == 0:
                print(f"downloaded {index}/{len(futures)}", flush=True)
    issues = validate_manifest(records, root=root)
    if issues:
        raise RuntimeError("manifest validation failed: " + "; ".join(issues))
    manifest_path = metadata / "raw-manifest.json"
    manifest_sha = write_manifest(manifest_path, records)
    sealed = [record for record in records if record.partition == "sealed-holdout"]
    seal = {
        "protocol_id": PROTOCOL_ID, "created_at": utc_now(), "manifest_sha256": manifest_sha,
        "sealed_file_count": len(sealed), "sealed_bytes": sum(row.size for row in sealed),
        "sealed_inventory": [{"path": row.path, "size": row.size, "sha256": row.sha256} for row in sorted(sealed, key=lambda row: row.path)],
    }
    atomic_bytes(metadata / "sealed-inventory.json", (json.dumps(seal, indent=2, sort_keys=True) + "\n").encode())
    summary = {
        "symbols": len(roster), "files": len(records), "bytes": sum(row.size for row in records),
        "development_files": sum(row.partition == "development" for row in records),
        "holdout_files": len(sealed), "holdout_bytes": sum(row.size for row in sealed),
        "manifest_sha256": manifest_sha,
    }
    atomic_bytes(metadata / "acquisition-summary.json", (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
