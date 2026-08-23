"""Supplement v2 builder for ALT-MULTITF-006 (frozen protocol H1).

Acquires and deterministically normalizes the inputs the 006 protocol adds on top of
the ALT-MULTITF-005 archives:
- BTCUSDT/ETHUSDT/DOTUSDT raw klines+funding for 2020-02..2026-08 (full history so
  that slow daily/weekly averages are warmed before the DEV window);
- all ten universe symbols for 2026-01..2026-08;
- a fresh public exchangeInfo snapshot taken at build time.

For the seven symbols supplied by the primary archive through 2025-12, normalization
stitches the already-extracted immutable raw zips from the merged primary tree with the
newly downloaded 2026 zips, producing one continuous normalized series per symbol and
timeframe (including 1w = 2016x5m buckets). Outputs land under the root
``altcoin-multitf-006-supplement`` with byte-deterministic encodings and manifests.

This module performs acquisition/hashing/normalization only. It never analyses any
window content beyond structural validation required for ingestion.
"""
from __future__ import annotations

import concurrent.futures
import gzip
import hashlib
import io
import json
import os
import tempfile
import tarfile
import time
import urllib.error
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from research.altcoin_multitf_supplement import (
    KLINE_HEADER,
    FUNDING_HEADER,
    SupplementError,
    _is_header,
    aggregate_bucket,
    atomic_write,
    canonical,
    fetch_retry,
    replace_write,
    sha256_file,
)

PROTOCOL_ID = "ALT-MULTITF-006"
ROOT_NAME = "altcoin-multitf-006-supplement"
SOURCE_REVISION = "ALT-MULTITF-006"
EXCHANGE_INFO_URL = "https://www.binance.com/fapi/v1/exchangeInfo"
VISION = "https://data.binance.vision/data/futures/um/monthly"

UNIVERSE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT")
FULL_HISTORY_SYMBOLS = ("BTCUSDT", "ETHUSDT", "DOTUSDT")
FULLHIST_FIRST_MONTH = (2020, 2)
EXTEND_LAST_MONTH = (2026, 8)
EXTEND_FIRST_MONTH = (2026, 1)
PRIMARY_ROOT = "altcoin-multitf-005"

# Raw-row structural validation bounds (generous ingestion envelope, UTC ms).
INGEST_START_MS = 1_580_515_200_000  # 2020-02-01
INGEST_END_EXCLUSIVE_MS = 1_786_075_200_000  # 2026-09-01
BAR_MS = 300_000
TIMEFRAMES = {"15m": 3, "30m": 6, "1h": 12, "2h": 24, "4h": 48, "1d": 288, "1w": 2016}


def month_range(first: tuple[int, int], last: tuple[int, int]) -> list[tuple[int, int]]:
    result = []
    year, month = first
    while (year, month) <= last:
        result.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def month_bounds(year: int, month: int) -> tuple[int, int]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    nxt = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc)
    return int(start.timestamp() * 1000), int(nxt.timestamp() * 1000)


def archive_url(symbol: str, datatype: str, year: int, month: int) -> str:
    if datatype == "klines":
        return f"{VISION}/klines/{symbol}/5m/{symbol}-5m-{year:04d}-{month:02d}.zip"
    return f"{VISION}/fundingRate/{symbol}/{symbol}-fundingRate-{year:04d}-{month:02d}.zip"


def plan_entries() -> list[dict]:
    entries = []
    for symbol in UNIVERSE_SYMBOLS:
        if symbol in FULL_HISTORY_SYMBOLS:
            months = month_range(FULLHIST_FIRST_MONTH, EXTEND_LAST_MONTH)
        else:
            months = month_range(EXTEND_FIRST_MONTH, EXTEND_LAST_MONTH)
        for datatype in ("klines", "funding"):
            for year, month in months:
                url = archive_url(symbol, datatype, year, month)
                start, end = month_bounds(year, month)
                entries.append({
                    "symbol": symbol,
                    "datatype": datatype,
                    "year": year,
                    "month": month,
                    "url": url,
                    "filename": Path(url).name,
                    "relative": str(Path(ROOT_NAME) / "development" / "raw" / datatype / symbol / Path(url).name),
                })
    return entries


def safe_zip_rows(path: Path):
    with zipfile.ZipFile(path) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) != 1:
            raise SupplementError(f"archive must contain exactly one file: {path}")
        member = members[0]
        pure = PurePosixPath(member.filename)
        if pure.is_absolute() or ".." in pure.parts or member.file_size > 1_000_000_000:
            raise SupplementError(f"unsafe ZIP member: {member.filename}")
        with archive.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
            yield from csv_rows(text)


def csv_rows(text):
    import csv as _csv
    yield from _csv.reader(text)


def validate_kline_row(row: list[str]) -> tuple[list[str] | None, str | None]:
    if len(row) < 11:
        return None, "schema"
    try:
        open_ms, close_ms = int(row[0]), int(row[6])
        values = [float(row[i]) for i in (1, 2, 3, 4, 5, 7, 9, 10)]
        trades = int(row[8])
    except (ValueError, OverflowError):
        return None, "numeric"
    if not INGEST_START_MS <= open_ms < INGEST_END_EXCLUSIVE_MS or close_ms != open_ms + BAR_MS - 1 or open_ms % BAR_MS:
        return None, "boundary"
    import math
    if not all(math.isfinite(v) and v >= 0 for v in values) or trades < 0:
        return None, "numeric"
    opn, high, low, close = values[:4]
    if low > min(opn, close) or high < max(opn, close) or high < low or min(opn, high, low, close) <= 0:
        return None, "ohlc"
    return [str(open_ms), *row[1:6], str(close_ms), *row[7:11]], None


def validate_funding_row(row: list[str]) -> tuple[list[str] | None, str | None]:
    if len(row) < 3:
        return None, "schema"
    try:
        timestamp = int(row[0])
        rate = float(row[2])
    except (ValueError, OverflowError):
        return None, "numeric"
    import math
    if not INGEST_START_MS <= timestamp < INGEST_END_EXCLUSIVE_MS or not math.isfinite(rate):
        return None, "boundary_or_numeric"
    return [str(timestamp), repr(rate)], None


def deterministic_gzip_csv(path: Path, header: list[str], rows) -> tuple[int, int | None, int | None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    os.close(fd)
    count = 0
    first = last = None
    try:
        with open(temporary_name, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                    import csv as _csv
                    writer = _csv.writer(text, lineterminator="\n")
                    writer.writerow(header)
                    for row in rows:
                        writer.writerow(row)
                        count += 1
                        ts = int(row[0])
                        first = ts if first is None else first
                        last = ts
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return count, first, last


def aggregate_timeframe(clean_rows: list[list[str]], factor: int):
    bucket: list[list[str]] = []
    bucket_start = None
    for row in clean_rows:
        timestamp = int(row[0])
        start = timestamp - timestamp % (factor * BAR_MS)
        if bucket_start is None or start == bucket_start:
            bucket.append(row)
            bucket_start = start
            continue
        if len(bucket) == factor and int(bucket[0][0]) == bucket_start and int(bucket[-1][0]) + BAR_MS == bucket_start + factor * BAR_MS:
            yield aggregate_bucket(bucket, bucket_start, factor)
        bucket, bucket_start = [row], start
    if bucket and len(bucket) == factor and int(bucket[0][0]) == bucket_start and int(bucket[-1][0]) + BAR_MS == bucket_start + factor * BAR_MS:
        yield aggregate_bucket(bucket, bucket_start, factor)


def acquire(workspace: Path, workers: int = 6) -> dict:
    root = workspace / "data"
    metadata = root / ROOT_NAME / "metadata"
    exchange_path = metadata / "exchangeInfo.raw.json"
    atomic_write(exchange_path, fetch_retry(EXCHANGE_INFO_URL))
    plan = plan_entries()
    atomic_write(metadata / "supplement2.acquisition.plan.json", canonical(plan))
    state_path = metadata / "supplement2.state.json"
    state = {}
    if state_path.exists():
        state = json.loads(state_path.read_text()).get("files", {})

    def one(entry: dict) -> dict | None:
        target = root / entry["relative"]
        saved = state.get(entry["relative"])
        if saved and target.is_file() and target.stat().st_size == saved["size"] and sha256_file(target) == saved["sha256"]:
            return saved
        target.unlink(missing_ok=True)
        try:
            payload = fetch_retry(entry["url"])
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise
        atomic_write(target, payload)
        record = {
            "path": entry["relative"],
            "size": target.stat().st_size,
            "sha256": sha256_file(target),
            "source_url": entry["url"],
        }
        state[entry["relative"]] = record
        return record

    downloaded = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for index, future in enumerate(concurrent.futures.as_completed([pool.submit(one, e) for e in plan]), 1):
            rec = future.result()
            if rec:
                downloaded.append(rec)
            if index % 40 == 0:
                replace_write(state_path, canonical({"files": state}))
                print(f"v2 acquire {index}/{len(plan)} present={len(downloaded)}", flush=True)
    replace_write(state_path, canonical({"files": state}))
    manifest = {
        "protocol_id": PROTOCOL_ID,
        "expected_requests": len(plan),
        "downloaded_files": sorted(downloaded, key=lambda r: r["path"]),
    }
    manifest_path = metadata / "supplement2.raw-manifest.json"
    atomic_write(manifest_path, canonical(manifest))
    return {"expected": len(plan), "downloaded": len(downloaded), "manifest_sha256": sha256_file(manifest_path)}


def _raw_sources_for_symbol(root: Path, primary_merged: Path | None, symbol: str, datatype: str) -> list[Path]:
    """Ordered raw zip paths: newly acquired v2 zips plus primary-archive zips."""
    sources = []
    own_dir = root / ROOT_NAME / "development" / "raw" / datatype / symbol
    if own_dir.exists():
        sources.extend(sorted(own_dir.glob("*.zip")))
    if primary_merged is not None:
        legacy = primary_merged / PRIMARY_ROOT / "development" / "raw" / datatype / symbol
        if legacy.exists():
            sources.extend(sorted(p for p in legacy.glob("*.zip") if p not in sources))
    return sorted(sources, key=lambda p: p.name)


def normalize(workspace: Path, primary_merged: Path | None) -> dict:
    root = workspace / "data"
    metadata = root / ROOT_NAME / "metadata"
    audit = {"invalid_rows": {}, "duplicates": 0, "out_of_order": 0}
    output_records = []
    built = "frozen-supplement-v2"
    for symbol in UNIVERSE_SYMBOLS:
        invalid: dict[str, int] = {}
        previous_ts = None
        clean_rows: list[list[str]] = []
        seen_ts: set[int] = set()
        for zip_path in _raw_sources_for_symbol(root, primary_merged, symbol, "klines"):
            for raw_row in safe_zip_rows(zip_path):
                if _is_header(raw_row):
                    continue
                row, issue = validate_kline_row(raw_row)
                if issue:
                    invalid[issue] = invalid.get(issue, 0) + 1
                    continue
                assert row is not None
                ts = int(row[0])
                if ts in seen_ts:
                    audit["duplicates"] += 1
                    continue
                if previous_ts is not None and ts <= previous_ts:
                    audit["out_of_order"] += 1
                    continue
                seen_ts.add(ts)
                clean_rows.append(row)
                previous_ts = ts
        if not clean_rows:
            raise SupplementError(f"no valid klines assembled for {symbol}")
        base_out = root / ROOT_NAME / "development" / "normalized" / "klines" / symbol
        count5, first5, last5 = deterministic_gzip_csv(base_out / f"{symbol}-5m.csv.gz", KLINE_HEADER, clean_rows)
        output_records.append({
            "path": str((base_out / f"{symbol}-5m.csv.gz").relative_to(root)), "rows": count5,
            "first_open_ms": first5, "last_close_ms": last5,
        })
        for tf_name, factor in TIMEFRAMES.items():
            target = base_out / f"{symbol}-{tf_name}.csv.gz"
            n, first_tf, last_tf = deterministic_gzip_csv(target, KLINE_HEADER, aggregate_timeframe(clean_rows, factor))
            output_records.append({"path": str(target.relative_to(root)), "rows": n, "timeframe": tf_name})
        funding_sources = _raw_sources_for_symbol(root, primary_merged, symbol, "funding")
        f_rows: list[list[str]] = []
        f_seen: set[int] = set()
        previous_f = None
        for zip_path in funding_sources:
            for raw_row in safe_zip_rows(zip_path):
                if _is_header(raw_row):
                    continue
                row, issue = validate_funding_row(raw_row)
                if issue:
                    invalid[f"funding_{issue}"] = invalid.get(f"funding_{issue}", 0) + 1
                    continue
                assert row is not None
                ts = int(row[0])
                if ts in f_seen or (previous_f is not None and ts <= previous_f):
                    continue
                f_seen.add(ts)
                f_rows.append(row)
                previous_f = ts
        f_out = root / ROOT_NAME / "development" / "normalized" / "funding" / symbol / f"{symbol}-funding.csv.gz"
        nf, ff, lf = deterministic_gzip_csv(f_out, FUNDING_HEADER, f_rows)
        output_records.append({"path": str(f_out.relative_to(root)), "rows": nf, "first_ms": ff, "last_ms": lf})
        audit["invalid_rows"][symbol] = invalid
        print(f"v2 normalized {symbol}: 5m rows={count5}", flush=True)
    normalized_manifest = {"protocol_id": PROTOCOL_ID, "built_at": built, "files": output_records, "audit": audit}
    manifest_path = metadata / "supplement2.normalized-manifest.json"
    atomic_write(manifest_path, canonical(normalized_manifest))
    return {"symbols": len(UNIVERSE_SYMBOLS), "files": len(output_records), "manifest_sha256": sha256_file(manifest_path)}


def extract_exchange_rules_v2(workspace: Path) -> dict:
    path = workspace / "data" / ROOT_NAME / "metadata" / "exchangeInfo.raw.json"
    payload = json.loads(path.read_text())
    rules = {}
    for item in payload.get("symbols", []):
        symbol = item.get("symbol")
        if symbol not in UNIVERSE_SYMBOLS:
            continue
        extracted = {"status": item.get("status"), "contract_type": item.get("contractType")}
        for filt in item.get("filters", []):
            kind = filt.get("filterType")
            if kind == "PRICE_FILTER":
                extracted["tick_size"] = float(filt["tickSize"])
            elif kind == "LOT_SIZE":
                extracted["step_size"] = float(filt["stepSize"])
                extracted["min_qty"] = float(filt["minQty"])
                extracted["max_qty"] = float(filt["maxQty"])
            elif kind == "MIN_NOTIONAL":
                extracted["min_notional"] = float(filt.get("notional") or filt.get("minNotional"))
        rules[symbol] = extracted
    missing = [s for s in UNIVERSE_SYMBOLS if s not in rules]
    if missing:
        raise SupplementError(f"symbols absent from exchangeInfo: {missing}")
    out = workspace / "data" / ROOT_NAME / "metadata" / "supplement2.exchange-rules.json"
    atomic_write(out, canonical(rules))
    return rules


def build_archive(workspace: Path) -> dict:
    dataset = (workspace / "data" / ROOT_NAME).resolve()
    output = (workspace / "release" / f"{ROOT_NAME}.tar.gz").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    entries = [dataset, *sorted(dataset.rglob("*"))]
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in entries:
                    info = archive.gettarinfo(str(path), arcname=str(path.relative_to(dataset.parent)))
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    if path.is_file():
                        with path.open("rb") as handle:
                            archive.addfile(info, handle)
                    else:
                        archive.addfile(info)
    return {"path": output.name, "size": output.stat().st_size, "sha256": sha256_file(output)}


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--primary-merged", type=Path, default=None, help="merged primary tree for raw stitching")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    acq = acquire(args.workspace, workers=args.workers)
    norm = normalize(args.workspace, args.primary_merged)
    rules = extract_exchange_rules_v2(args.workspace)
    arch = build_archive(args.workspace)
    print(json.dumps({"acquisition": acq, "normalization": norm, "archive": arch}, indent=2, sort_keys=True))
    sys.exit(0)
