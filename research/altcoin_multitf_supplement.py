"""Supplemental immutable dataset builder for ALTCOIN_MULTITF_005 Phase 4 Part 2.

Builds a deterministic, portable supplement archive for frozen-universe symbols that
are absent from the primary ALT-MULTITF-005 archive, restricted to the development
interval. The evaluation interval is never downloaded, stored or referenced.

The module performs no account-specific access: every source is a public endpoint.
All outputs are byte-deterministic (gzip mtime=0, tar mtime=0, sorted entries).
"""
from __future__ import annotations

import concurrent.futures
import csv
import gzip
import hashlib
import io
import json
import math
import os
import tempfile
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

PROTOCOL_ID = "ALT-MULTITF-005"
ROOT_NAME = "altcoin-multitf-005-supplement"
SOURCE_REVISION = "ALT-MULTITF-005"
SUPPLEMENT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "DOTUSDT")
UNIVERSE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT")
# Frozen development interval: 2021-01-01T00:00:00Z .. 2023-12-31T23:59:59Z.
DEV_START_MS = 1_609_459_200_000
DEV_END_EXCLUSIVE_MS = 1_704_067_200_000
BAR_MS = 300_000
TIMEFRAMES = {"15m": 3, "30m": 6, "1h": 12, "2h": 24, "4h": 48, "1d": 288}
EXCHANGE_INFO_URL = "https://www.binance.com/fapi/v1/exchangeInfo"
VISION = "https://data.binance.vision/data/futures/um/monthly"
KLINE_HEADER = ["open_time_ms", "open", "high", "low", "close", "volume", "close_time_ms", "quote_volume", "trade_count", "taker_buy_base", "taker_buy_quote"]
FUNDING_HEADER = ["funding_time_ms", "funding_rate", "mark_price"]
STATE_VERSION = 1


class SupplementError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileRecord:
    path: str
    size: int
    sha256: str
    symbol: str
    datatype: str
    timeframe: str | None
    start_ms: int | None
    end_exclusive_ms: int | None
    source_inputs: tuple[str, ...]
    built_at: str


def canonical(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"immutable artifact conflict: {path}")
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


def replace_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, *, timeout: int = 180) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"{PROTOCOL_ID}/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    if not payload:
        raise RuntimeError(f"empty response: {url}")
    return payload


def fetch_retry(url: str, attempts: int = 6) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return fetch(url)
        except urllib.error.HTTPError:
            raise
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            last = exc
            time.sleep(min(30, 2**attempt))
    raise SupplementError(f"download failed after {attempts} attempts: {url}: {last}")


def dev_months() -> list[tuple[int, int]]:
    result = []
    for year in (2021, 2022, 2023):
        for month in range(1, 13):
            result.append((year, month))
    return result


def month_bounds(year: int, month: int) -> tuple[int, int]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    next_date = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc)
    return int(start.timestamp() * 1000), int(next_date.timestamp() * 1000)


def archive_url(symbol: str, datatype: str, year: int, month: int) -> str:
    if datatype == "klines":
        return f"{VISION}/klines/{symbol}/5m/{symbol}-5m-{year:04d}-{month:02d}.zip"
    return f"{VISION}/fundingRate/{symbol}/{symbol}-fundingRate-{year:04d}-{month:02d}.zip"


def assert_development_path(path: Path) -> None:
    parts = set(path.resolve().parts)
    if "sealed-holdout" in parts or "holdout" in parts or "evaluation" in parts:
        raise SupplementError(f"non-development path rejected: {path}")


def safe_zip_rows(path: Path):
    assert_development_path(path)
    with zipfile.ZipFile(path) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) != 1:
            raise SupplementError(f"archive must contain exactly one file: {path}")
        member = members[0]
        pure = PurePosixPath(member.filename)
        if pure.is_absolute() or ".." in pure.parts or member.file_size > 1_000_000_000:
            raise SupplementError(f"unsafe ZIP member: {member.filename}")
        with archive.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
            yield from csv.reader(text)


def _is_header(row: list[str]) -> bool:
    if not row:
        return True
    try:
        int(row[0])
        return False
    except ValueError:
        return True


def validate_kline(row: list[str]) -> tuple[list[str] | None, str | None]:
    if len(row) < 11:
        return None, "schema"
    try:
        open_ms, close_ms = int(row[0]), int(row[6])
        values = [float(row[index]) for index in (1, 2, 3, 4, 5, 7, 9, 10)]
        trades = int(row[8])
    except (ValueError, OverflowError):
        return None, "numeric"
    if not DEV_START_MS <= open_ms < DEV_END_EXCLUSIVE_MS or close_ms != open_ms + BAR_MS - 1 or open_ms % BAR_MS:
        return None, "boundary"
    if not all(math.isfinite(value) and value >= 0 for value in values) or trades < 0:
        return None, "numeric"
    opn, high, low, close = values[:4]
    if low > min(opn, close) or high < max(opn, close) or high < low or min(opn, high, low, close) <= 0:
        return None, "ohlc"
    return [str(open_ms), *row[1:6], str(close_ms), *row[7:11]], None


def validate_funding(row: list[str]) -> tuple[list[str] | None, str | None]:
    if len(row) < 3:
        return None, "schema"
    try:
        timestamp = int(row[0])
        rate = float(row[2])
        mark = float(row[3]) if len(row) > 3 and row[3] else float("nan")
    except (ValueError, OverflowError):
        return None, "numeric"
    if not DEV_START_MS <= timestamp < DEV_END_EXCLUSIVE_MS:
        return None, "boundary"
    if not math.isfinite(rate) or (not math.isnan(mark) and (not math.isfinite(mark) or mark <= 0)):
        return None, "numeric"
    return [str(timestamp), repr(rate), "" if math.isnan(mark) else repr(mark)], None


def deterministic_gzip_csv(path: Path, header: list[str], rows) -> tuple[int, int | None, int | None]:
    assert_development_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    os.close(fd)
    count = 0
    first = last = None
    try:
        with open(temporary_name, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                    writer = csv.writer(text, lineterminator="\n")
                    writer.writerow(header)
                    for row in rows:
                        writer.writerow(row)
                        count += 1
                        timestamp = int(row[0])
                        first = timestamp if first is None else first
                        last = timestamp
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return count, first, last


def aggregate_bucket(rows: list[list[str]], start: int, factor: int) -> list[str]:
    return [
        str(start),
        rows[0][1],
        repr(max(float(row[2]) for row in rows)),
        repr(min(float(row[3]) for row in rows)),
        rows[-1][4],
        repr(sum(float(row[5]) for row in rows)),
        str(start + factor * BAR_MS - 1),
        repr(sum(float(row[7]) for row in rows)),
        str(sum(int(row[8]) for row in rows)),
        repr(sum(float(row[9]) for row in rows)),
        repr(sum(float(row[10]) for row in rows)),
    ]


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


def acquire_raw(workspace: Path, workers: int = 8) -> dict:
    root = workspace / "data"
    base = root / ROOT_NAME
    metadata = base / "metadata"
    exchange_path = metadata / "exchangeInfo.raw.json"
    if not exchange_path.exists():
        atomic_write(exchange_path, fetch_retry(EXCHANGE_INFO_URL))
    snapshot = {
        "protocol_id": PROTOCOL_ID,
        "root_name": ROOT_NAME,
        "source_revision": SOURCE_REVISION,
        "selection": "frozen Phase 4 universe symbols missing from the primary ALT-MULTITF-005 archive; development interval only",
        "symbols": list(SUPPLEMENT_SYMBOLS),
        "development_interval": ["2021-01-01T00:00:00Z", "2023-12-31T23:59:59Z"],
        "evaluation_interval_included": False,
        "exchange_info_url": EXCHANGE_INFO_URL,
    }
    plan = [
        [symbol, datatype, year, month, *month_bounds(year, month), archive_url(symbol, datatype, year, month)]
        for symbol in SUPPLEMENT_SYMBOLS
        for datatype in ("klines", "funding")
        for year, month in dev_months()
    ]
    atomic_write(metadata / "supplement.roster.snapshot.json", canonical(snapshot))
    atomic_write(metadata / "supplement.acquisition.plan.json", canonical(plan))

    state_path = metadata / "supplement.state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"state_version": STATE_VERSION, "files": {}}
    if state.get("state_version") != STATE_VERSION:
        raise SupplementError("incompatible supplement checkpoint")

    def one(item: list) -> dict | None:
        symbol, datatype, year, month, start, end, url = item
        relative = str(Path(ROOT_NAME) / "development" / "raw" / datatype / symbol / Path(url).name)
        target = root / relative
        assert_development_path(target)
        saved = state["files"].get(relative)
        if saved and target.is_file() and target.stat().st_size == saved["size"] and sha256_file(target) == saved["sha256"]:
            return saved
        target.unlink(missing_ok=True)
        try:
            payload = fetch_retry(url)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise
        atomic_write(target, payload)
        record = FileRecord(
            relative,
            target.stat().st_size,
            sha256_file(target),
            symbol,
            datatype,
            "5m" if datatype == "klines" else None,
            max(start, DEV_START_MS),
            min(end, DEV_END_EXCLUSIVE_MS),
            (url,),
            "frozen-supplement",
        )
        entry = asdict(record)
        entry["source_inputs"] = list(entry["source_inputs"])
        state["files"][relative] = entry
        return entry

    records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, item) for item in plan]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            record = future.result()
            if record:
                records.append(record)
            if index % 24 == 0:
                replace_write(state_path, canonical(state))
    expected = len(plan)
    found = len(records)
    replace_write(state_path, canonical(state))
    records.sort(key=lambda row: row["path"])
    manifest = {"protocol_id": PROTOCOL_ID, "partition": "development", "created_at": "frozen-supplement", "expected_requests": expected, "files": records}
    manifest_path = metadata / "supplement.raw-development-manifest.json"
    atomic_write(manifest_path, canonical(manifest))
    return {"expected_requests": expected, "files": found, "bytes": sum(row["size"] for row in records), "manifest_sha256": sha256_file(manifest_path)}


def normalize(workspace: Path) -> dict:
    root = workspace / "data"
    base = root / ROOT_NAME
    metadata = base / "metadata"
    manifest_path = metadata / "supplement.raw-development-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for record in manifest["files"]:
        path = root / record["path"]
        assert_development_path(path)
        if not path.is_file() or path.stat().st_size != record["size"] or sha256_file(path) != record["sha256"]:
            raise SupplementError(f"raw checksum mismatch: {record['path']}")
    audit = {
        "duplicates": 0,
        "conflicting_duplicates": 0,
        "invalid_rows": {},
        "out_of_order": 0,
        "gaps_over_30m": 0,
        "gap_intervals": [],
        "missing_development_histories": [],
    }
    output_records: list[FileRecord] = []
    row_counts = {"5m": 0, "funding": 0, **{tf: 0 for tf in TIMEFRAMES}}
    built = "frozen-supplement"
    for symbol in SUPPLEMENT_SYMBOLS:
        symbol_raw = [record for record in manifest["files"] if record["symbol"] == symbol]
        klines = sorted((record for record in symbol_raw if record["datatype"] == "klines"), key=lambda item: item["start_ms"] or 0)
        funding = sorted((record for record in symbol_raw if record["datatype"] == "funding"), key=lambda item: item["start_ms"] or 0)
        if not klines:
            audit["missing_development_histories"].append(symbol)
            continue
        invalid: dict[str, int] = {}
        previous_ts = None
        previous_row = None
        clean_rows: list[list[str]] = []
        for record in klines:
            for raw_row in safe_zip_rows(root / record["path"]):
                if _is_header(raw_row):
                    continue
                row, issue = validate_kline(raw_row)
                if issue:
                    invalid[issue] = invalid.get(issue, 0) + 1
                    continue
                assert row is not None
                timestamp = int(row[0])
                if previous_ts is not None and timestamp < previous_ts:
                    audit["out_of_order"] += 1
                    continue
                if timestamp == previous_ts:
                    if row == previous_row:
                        audit["duplicates"] += 1
                    else:
                        audit["conflicting_duplicates"] += 1
                    continue
                if previous_ts is not None and timestamp - previous_ts > 6 * BAR_MS:
                    audit["gaps_over_30m"] += 1
                    audit["gap_intervals"].append({"symbol": symbol, "after_ms": previous_ts, "next_ms": timestamp, "missing_bars": (timestamp - previous_ts) // BAR_MS - 1})
                clean_rows.append(row)
                previous_ts, previous_row = timestamp, row
        if audit["conflicting_duplicates"]:
            raise SupplementError("conflicting duplicate bars found; fail closed")
        audit["invalid_rows"][symbol] = invalid
        five_path = base / "development" / "normalized" / "klines" / symbol / f"{symbol}-5m.csv.gz"
        count, first_bar, last_bar = deterministic_gzip_csv(five_path, KLINE_HEADER, clean_rows)
        row_counts["5m"] += count
        sources = tuple(record["path"] for record in klines)
        output_records.append(FileRecord(str(five_path.relative_to(root)), five_path.stat().st_size, sha256_file(five_path), symbol, "klines", "5m", first_bar, None if last_bar is None else last_bar + BAR_MS, sources, built))
        for timeframe, factor in TIMEFRAMES.items():
            target = base / "development" / "normalized" / "klines" / symbol / f"{symbol}-{timeframe}.csv.gz"
            n, start_tf, finish_tf = deterministic_gzip_csv(target, KLINE_HEADER, aggregate_timeframe(clean_rows, factor))
            row_counts[timeframe] += n
            output_records.append(FileRecord(str(target.relative_to(root)), target.stat().st_size, sha256_file(target), symbol, "klines", timeframe, start_tf, None if finish_tf is None else finish_tf + factor * BAR_MS, (str(five_path.relative_to(root)),), built))
        funding_rows: list[list[str]] = []
        seen_funding: dict[int, list[str]] = {}
        for record in funding:
            for raw_row in safe_zip_rows(root / record["path"]):
                if _is_header(raw_row):
                    continue
                row, issue = validate_funding(raw_row)
                if issue:
                    invalid[f"funding_{issue}"] = invalid.get(f"funding_{issue}", 0) + 1
                    continue
                assert row is not None
                timestamp = int(row[0])
                if timestamp in seen_funding:
                    if seen_funding[timestamp] == row:
                        audit["duplicates"] += 1
                    else:
                        raise SupplementError(f"conflicting funding duplicate: {symbol} {timestamp}")
                    continue
                seen_funding[timestamp] = row
                funding_rows.append(row)
        funding_rows.sort(key=lambda row: int(row[0]))
        funding_path = base / "development" / "normalized" / "funding" / symbol / f"{symbol}-funding.csv.gz"
        n_funding, first_funding, last_funding = deterministic_gzip_csv(funding_path, FUNDING_HEADER, funding_rows)
        row_counts["funding"] += n_funding
        output_records.append(FileRecord(str(funding_path.relative_to(root)), funding_path.stat().st_size, sha256_file(funding_path), symbol, "funding", None, first_funding, None if last_funding is None else last_funding + 1, tuple(record["path"] for record in funding), built))
        audit["invalid_rows"][symbol] = invalid
    audit["invalid_row_total"] = sum(sum(values.values()) for values in audit["invalid_rows"].values())
    normalized_manifest = {"protocol_id": PROTOCOL_ID, "partition": "development", "built_at": built, "files": [asdict(item) for item in output_records]}
    normalized_manifest_path = metadata / "supplement.normalized-development-manifest.json"
    atomic_write(normalized_manifest_path, canonical(normalized_manifest))
    atomic_write(base / "development" / "audit" / "quality.json", canonical(audit))
    return {"verification_manifest_sha256": sha256_file(manifest_path), "rows": row_counts, "files": len(output_records), "bytes": sum(item.size for item in output_records), **audit}


def extract_exchange_rules(workspace: Path, symbols: tuple[str, ...] = UNIVERSE_SYMBOLS) -> dict:
    """Deterministic per-symbol exchange rule extraction from the saved snapshot.

    Covers the full frozen universe so that a single immutable public snapshot
    supplies execution metadata for every symbol, including the seven supplied by
    the primary archive (which does not embed exchangeInfo).
    """
    workspace = workspace.resolve()
    path = workspace / "data" / ROOT_NAME / "metadata" / "exchangeInfo.raw.json"
    payload = json.loads(path.read_text())
    rules = {}
    for item in payload.get("symbols", []):
        symbol = item.get("symbol")
        if symbol not in symbols:
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
    missing = [symbol for symbol in symbols if symbol not in rules]
    if missing:
        raise SupplementError(f"symbols absent from exchangeInfo snapshot: {missing}")
    for symbol, values in rules.items():
        required = ("tick_size", "step_size", "min_qty", "min_notional")
        if any(not math.isfinite(values.get(key, float("nan"))) or values[key] <= 0 for key in required):
            raise SupplementError(f"incomplete exchange rules for {symbol}: {values}")
    out_path = workspace / "data" / ROOT_NAME / "metadata" / "supplement.exchange-rules.json"
    atomic_write(out_path, canonical(rules))
    return rules


def build_supplement_archive(workspace: Path) -> dict:
    dataset = (workspace / "data" / ROOT_NAME).resolve()
    output = (workspace / "release" / f"{ROOT_NAME}.tar.gz").resolve()
    assert_development_path(dataset)
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


def build_metadata_summary(workspace: Path, acquisition: dict, normalization: dict, archive: dict) -> dict:
    workspace = workspace.resolve()
    rules = json.loads((workspace / "data" / ROOT_NAME / "metadata" / "supplement.exchange-rules.json").read_text())
    summary = {
        "protocol_id": PROTOCOL_ID,
        "root_name": ROOT_NAME,
        "source_revision": SOURCE_REVISION,
        "purpose": "supplemental immutable inputs for frozen Phase 4 universe symbols absent from the primary archive",
        "symbols": list(SUPPLEMENT_SYMBOLS),
        "development_interval_utc": ["2021-01-01T00:00:00Z", "2023-12-31T23:59:59Z"],
        "evaluation_data_included": False,
        "sources": {
            "exchange_info": EXCHANGE_INFO_URL,
            "klines_pattern": f"{VISION}/klines/{{SYMBOL}}/5m/{{SYMBOL}}-5m-YYYY-MM.zip",
            "funding_pattern": f"{VISION}/fundingRate/{{SYMBOL}}/{{SYMBOL}}-fundingRate-YYYY-MM.zip",
        },
        "exchange_rules": rules,
        "acquisition": acquisition,
        "normalization": normalization,
        "archive": archive,
    }
    out = workspace / "release" / "supplement-summary.json"
    atomic_write(out, canonical(summary))
    return summary


def run(workspace: Path, *, workers: int = 8) -> dict:
    acquisition = acquire_raw(workspace, workers=workers)
    normalization = normalize(workspace)
    rules = extract_exchange_rules(workspace)
    archive = build_supplement_archive(workspace)
    summary = build_metadata_summary(workspace, acquisition, normalization, archive)
    return {"acquisition": acquisition, "normalization": normalization, "rules": rules, "archive": archive, "summary_path": str(summary["archive"])}


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path(".alt-multitf-005-supplement"))
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    result = run(args.workspace, workers=args.workers)
    print(json.dumps(result, indent=2, sort_keys=True))
    sys.exit(0)
