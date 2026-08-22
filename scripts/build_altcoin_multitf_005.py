from __future__ import annotations

import argparse
import concurrent.futures
import csv
import gzip
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import time
import urllib.error
import sys
from dataclasses import asdict
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import research.altcoin_multitf_compact as compact
from scripts.rebuild_altcoin_multitf_004 import FROZEN_ROSTER

PROTOCOL_ID = "ALT-MULTITF-005"
ROOT_NAME = "altcoin-multitf-005"
STATE_VERSION = 1
SPEC = {
    "protocol_id": PROTOCOL_ID,
    "root_name": ROOT_NAME,
    "source_revision": "ALT-MULTITF-004",
    "start_ms": compact.START_MS,
    "end_exclusive_ms": compact.END_MS,
    "timeframes": ["5m", *compact.TIMEFRAMES],
    "symbols": list(FROZEN_ROSTER),
    "inventory_files": 3291,
    "inventory_bytes": 568466246,
}
CONFIG_HASH = hashlib.sha256(compact.canonical(SPEC)).hexdigest()

# Reuse the audited normalization/eligibility implementation under a new immutable root.
def deterministic_gzip_csv(path: Path, header: list[str], rows) -> tuple[int, int | None, int | None]:
    compact.assert_development_path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent); os.close(fd)
    count = 0; first = last = None
    try:
        with open(temporary_name, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as compressed:
                import io
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                    writer = csv.writer(text, lineterminator="\n"); writer.writerow(header)
                    for row in rows:
                        writer.writerow(row); count += 1
                        timestamp = int(row[0]); first = timestamp if first is None else first; last = timestamp
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name): os.unlink(temporary_name)
    return count, first, last


def _state_path(workspace: Path) -> Path:
    return workspace / "checkpoint" / "state.json"


def new_state() -> dict:
    return {"state_version": STATE_VERSION, "protocol_id": PROTOCOL_ID, "config_hash": CONFIG_HASH, "completed": {}, "files": {}}


def load_state(workspace: Path) -> dict:
    path = _state_path(workspace)
    if not path.exists():
        return new_state()
    state = json.loads(path.read_text(encoding="utf-8"))
    expected = (STATE_VERSION, PROTOCOL_ID, CONFIG_HASH)
    actual = (state.get("state_version"), state.get("protocol_id"), state.get("config_hash"))
    if actual != expected:
        raise RuntimeError(f"incompatible checkpoint: {actual!r} != {expected!r}")
    return state


def save_state(workspace: Path, state: dict) -> None:
    compact.atomic_write(_state_path(workspace), compact.canonical(state)) if not _state_path(workspace).exists() else _replace(_state_path(workspace), compact.canonical(state))


def _replace(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def verified(path: Path, record: dict | None) -> bool:
    return bool(record and path.is_file() and path.stat().st_size == record["size"] and compact.sha256_file(path) == record["sha256"])


def fetch_retry(url: str, attempts: int = 8) -> bytes:
    for attempt in range(attempts):
        try:
            return compact.fetch(url, timeout=180)
        except urllib.error.HTTPError as error:
            if error.code not in {408, 425, 429, 500, 502, 503, 504} or attempt + 1 == attempts:
                raise
            retry_after = error.headers.get("Retry-After") if error.headers else None
            delay = float(retry_after) if retry_after and retry_after.isdigit() else min(60, 2 ** attempt)
            time.sleep(delay)
        except (OSError, TimeoutError, urllib.error.URLError):
            if attempt + 1 == attempts:
                raise
            time.sleep(min(60, 2 ** attempt))
    raise AssertionError("unreachable")


def prepare(workspace: Path, state: dict) -> None:
    metadata = workspace / "data" / ROOT_NAME / "metadata"
    snapshot = {
        "protocol_id": PROTOCOL_ID,
        "selection": "frozen roster inherited from ALT-MULTITF-004; never reselected",
        "symbol_count": len(FROZEN_ROSTER),
        "symbols": list(FROZEN_ROSTER),
        "source_revision": "ALT-MULTITF-004",
    }
    plan = [(s, d, y, m, start, end, compact.archive_url(s, d, y, m)) for s in FROZEN_ROSTER for d in ("klines", "funding") for y, m, start, end in compact.months()]
    for path, value in ((metadata / "roster.snapshot.json", snapshot), (metadata / "acquisition.plan.json", plan), (metadata / "build-spec.json", SPEC)):
        payload = compact.canonical(value)
        if path.exists() and path.read_bytes() != payload: raise RuntimeError(f"immutable metadata conflict: {path}")
        compact.atomic_write(path, payload)
    state["completed"]["prepare"] = True; save_state(workspace, state)


def acquire(workspace: Path, state: dict, workers: int) -> dict:
    root = workspace / "data"; base = root / ROOT_NAME
    plan = json.loads((base / "metadata" / "acquisition.plan.json").read_text())

    def one(item: list) -> dict | None:
        symbol, datatype, year, month, start, end, url = item
        relative = str(Path(ROOT_NAME) / "development" / "raw" / datatype / symbol / Path(url).name)
        target = root / relative; compact.assert_development_path(target)
        saved = state["files"].get(relative)
        if verified(target, saved): return saved
        target.unlink(missing_ok=True)
        try: compact.atomic_write(target, fetch_retry(url))
        except urllib.error.HTTPError as error:
            if error.code == 404: return None
            raise
        return asdict(compact.FileRecord(relative, target.stat().st_size, compact.sha256_file(target), symbol, datatype, "5m" if datatype == "klines" else None, start, end, (url,), "frozen-resume"))

    records: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, item) for item in plan]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            record = future.result()
            if record:
                records.append(record); state["files"][record["path"]] = record
            if index % 50 == 0:
                save_state(workspace, state); print(f"checked {index}/{len(futures)} present={len(records)}", flush=True)
    records.sort(key=lambda row: row["path"])
    manifest = {"protocol_id": PROTOCOL_ID, "partition": "development", "created_at": "frozen-resume", "files": records}
    manifest_path = base / "metadata" / "raw-development-manifest.json"; _replace(manifest_path, compact.canonical(manifest))
    result = {"symbols": len(FROZEN_ROSTER), "files": len(records), "bytes": sum(row["size"] for row in records), "manifest_sha256": compact.sha256_file(manifest_path)}
    if result["files"] != SPEC["inventory_files"] or result["bytes"] != SPEC["inventory_bytes"]: raise RuntimeError(f"frozen inventory mismatch: {result}")
    state["completed"]["acquire"] = result; save_state(workspace, state); return result


def deterministic_archive(dataset: Path, output: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as raw:
        import gzip
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in [dataset, *sorted(dataset.rglob("*"))]:
                    info = archive.gettarinfo(str(path), arcname=str(path.relative_to(dataset.parent)))
                    info.uid = info.gid = 0; info.uname = info.gname = ""; info.mtime = 0
                    if path.is_file():
                        with path.open("rb") as handle: archive.addfile(info, handle)
                    else: archive.addfile(info)
    return {"path": str(output), "size": output.stat().st_size, "sha256": compact.sha256_file(output)}


def run(workspace: Path, mode: str, workers: int) -> dict:
    compact.assert_development_path(workspace / "data" / ROOT_NAME / "development")
    if mode == "restart": shutil.rmtree(workspace, ignore_errors=True)
    state = load_state(workspace); prepare(workspace, state)
    acquisition = acquire(workspace, state, workers)
    root = workspace / "data"
    old_protocol, old_root, old_gzip = compact.PROTOCOL_ID, compact.ROOT_NAME, compact._gzip_csv
    compact.PROTOCOL_ID, compact.ROOT_NAME, compact._gzip_csv = PROTOCOL_ID, ROOT_NAME, deterministic_gzip_csv
    try:
        raw_verification = compact.verify_raw_manifest(root)
        state["completed"]["raw_verification"] = raw_verification; save_state(workspace, state)
        if not state["completed"].get("normalize"):
            state["completed"]["normalize"] = compact.normalize(root); save_state(workspace, state)
        if not state["completed"].get("eligibility"):
            state["completed"]["eligibility"] = compact.eligibility(root); save_state(workspace, state)
    finally:
        compact.PROTOCOL_ID, compact.ROOT_NAME, compact._gzip_csv = old_protocol, old_root, old_gzip
    archive = deterministic_archive(root / ROOT_NAME, workspace / "release" / f"{ROOT_NAME}.tar.gz")
    state["completed"]["archive"] = archive; save_state(workspace, state)
    result = {"protocol_id": PROTOCOL_ID, "config_hash": CONFIG_HASH, "acquisition": acquisition, "raw_verification": raw_verification, "archive": archive}
    _replace(workspace / "release" / "build-result.json", compact.canonical(result)); return result


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--workspace", type=Path, default=Path(".alt-multitf-005")); parser.add_argument("--mode", choices=("resume", "restart"), default="resume"); parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args(); print(json.dumps(run(args.workspace, args.mode, args.workers), indent=2, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
