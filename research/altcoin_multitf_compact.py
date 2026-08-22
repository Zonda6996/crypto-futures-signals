from __future__ import annotations

import argparse
import concurrent.futures
import csv
import gzip
import hashlib
import io
import json
import math
import os
import statistics
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator

PROTOCOL_ID = "ALT-MULTITF-004"
ROOT_NAME = "altcoin-multitf-004"
START_MS = 1_577_836_800_000  # 2020-01-01 UTC
END_MS = 1_767_225_600_000  # 2026-01-01 UTC, exclusive
BAR_MS = 300_000
DAY_MS = 86_400_000
EXCHANGE_INFO_URL = "https://www.binance.com/fapi/v1/exchangeInfo"
TICKER_URL = "https://www.binance.com/fapi/v1/ticker/24hr"
VISION = "https://data.binance.vision/data/futures/um/monthly"
TIMEFRAMES = {"15m": 3, "30m": 6, "1h": 12, "2h": 24, "4h": 48, "1d": 288}
KLINE_HEADER = ["open_time_ms", "open", "high", "low", "close", "volume", "close_time_ms", "quote_volume", "trade_count", "taker_buy_base", "taker_buy_quote"]
FUNDING_HEADER = ["funding_time_ms", "funding_rate", "mark_price"]


class BoundaryError(RuntimeError):
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def fetch(url: str, *, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"{PROTOCOL_ID}/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    if not payload:
        raise RuntimeError(f"empty response: {url}")
    return payload


def assert_development_path(path: Path) -> None:
    parts = set(path.resolve().parts)
    if "sealed-holdout" in parts or "holdout" in parts:
        raise BoundaryError(f"holdout path rejected: {path}")


def select_roster(exchange_payload: bytes, ticker_payload: bytes, *, count: int = 40) -> tuple[list[str], dict]:
    exchange = json.loads(exchange_payload)
    ticker = json.loads(ticker_payload)
    eligible = {
        item["symbol"]: item
        for item in exchange.get("symbols", [])
        if item.get("contractType") == "PERPETUAL"
        and item.get("quoteAsset") == "USDT"
        and item.get("marginAsset") == "USDT"
        and item.get("status") == "TRADING"
        and item.get("symbol") not in {"BTCUSDT", "ETHUSDT"}
    }
    ranked = []
    for row in ticker:
        symbol = row.get("symbol")
        if symbol not in eligible:
            continue
        try:
            volume = float(row["quoteVolume"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(volume) and volume >= 0:
            ranked.append((symbol, volume))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    if len(ranked) < count:
        raise RuntimeError(f"only {len(ranked)} eligible ticker rows for top {count}")
    symbols = [symbol for symbol, _ in ranked[:count]]
    snapshot = {
        "protocol_id": PROTOCOL_ID,
        "selection": "top 40 by official ticker/24hr quoteVolume; TRADING USDT-margined PERPETUAL; BTCUSDT and ETHUSDT excluded; symbol ascending tie-break",
        "symbol_count": count,
        "symbols": symbols,
        "ranking": [{"rank": index + 1, "symbol": symbol, "quote_volume": volume} for index, (symbol, volume) in enumerate(ranked)],
        "exchange_info_sha256": hashlib.sha256(exchange_payload).hexdigest(),
        "ticker_24hr_sha256": hashlib.sha256(ticker_payload).hexdigest(),
    }
    return symbols, snapshot


def months() -> Iterator[tuple[int, int, int, int]]:
    year, month = 2020, 1
    while (year, month) < (2026, 1):
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        next_date = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc)
        yield year, month, int(start.timestamp() * 1000), int(next_date.timestamp() * 1000)
        year, month = next_date.year, next_date.month


def archive_url(symbol: str, datatype: str, year: int, month: int) -> str:
    if datatype == "klines":
        return f"{VISION}/klines/{symbol}/5m/{symbol}-5m-{year:04d}-{month:02d}.zip"
    return f"{VISION}/fundingRate/{symbol}/{symbol}-fundingRate-{year:04d}-{month:02d}.zip"


def safe_zip_rows(path: Path) -> Iterator[list[str]]:
    assert_development_path(path)
    with zipfile.ZipFile(path) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) != 1:
            raise RuntimeError(f"archive must contain exactly one file: {path}")
        member = members[0]
        pure = PurePosixPath(member.filename)
        if pure.is_absolute() or ".." in pure.parts or member.file_size > 1_000_000_000:
            raise RuntimeError(f"unsafe ZIP member: {member.filename}")
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
    if not START_MS <= open_ms < END_MS or close_ms != open_ms + BAR_MS - 1 or open_ms % BAR_MS:
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
        timestamp = int(row[0]); rate = float(row[2]); mark = float(row[3]) if len(row) > 3 and row[3] else float("nan")
    except (ValueError, OverflowError):
        return None, "numeric"
    if not START_MS <= timestamp < END_MS:
        return None, "boundary"
    if not math.isfinite(rate) or (not math.isnan(mark) and (not math.isfinite(mark) or mark <= 0)):
        return None, "numeric"
    return [str(timestamp), repr(rate), "" if math.isnan(mark) else repr(mark)], None


def download(root: Path, *, workers: int = 16) -> dict:
    metadata = root / ROOT_NAME / "metadata"
    exchange_path, ticker_path = metadata / "exchangeInfo.raw.json", metadata / "ticker24hr.raw.json"
    if exchange_path.exists() != ticker_path.exists():
        raise RuntimeError("incomplete immutable selection inputs")
    if exchange_path.exists():
        exchange_payload, ticker_payload = exchange_path.read_bytes(), ticker_path.read_bytes()
    else:
        exchange_payload, ticker_payload = fetch(EXCHANGE_INFO_URL), fetch(TICKER_URL)
        atomic_write(exchange_path, exchange_payload); atomic_write(ticker_path, ticker_payload)
    symbols, snapshot = select_roster(exchange_payload, ticker_payload)
    snapshot["acquired_at"] = snapshot.get("acquired_at") or utc_now()
    snapshot_path = metadata / "roster.snapshot.json"
    if snapshot_path.exists():
        saved = json.loads(snapshot_path.read_text())
        snapshot["acquired_at"] = saved["acquired_at"]
        if snapshot != saved:
            raise RuntimeError("frozen roster mismatch")
    else:
        atomic_write(snapshot_path, canonical(snapshot))
    plan = [(symbol, datatype, year, month, start, end, archive_url(symbol, datatype, year, month)) for symbol in symbols for datatype in ("klines", "funding") for year, month, start, end in months()]
    atomic_write(metadata / "acquisition.plan.json", canonical(plan))

    def one(item: tuple) -> FileRecord | None:
        symbol, datatype, year, month, start, end, url = item
        target = root / ROOT_NAME / "development" / "raw" / datatype / symbol / Path(url).name
        assert_development_path(target)
        if not target.exists():
            try:
                payload = fetch(url)
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                raise
            atomic_write(target, payload)
        return FileRecord(str(target.relative_to(root)), target.stat().st_size, sha256_file(target), symbol, datatype, "5m" if datatype == "klines" else None, start, end, (url,), utc_now())

    records: list[FileRecord] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(one, item) for item in plan]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            record = future.result()
            if record: records.append(record)
            if index % 250 == 0: print(f"checked {index}/{len(futures)}, present {len(records)}", flush=True)
    records.sort(key=lambda item: item.path)
    manifest = {"protocol_id": PROTOCOL_ID, "partition": "development", "created_at": utc_now(), "files": [asdict(item) for item in records]}
    atomic_write(metadata / "raw-development-manifest.json", canonical(manifest))
    return {"symbols": len(symbols), "files": len(records), "bytes": sum(item.size for item in records)}


def _gzip_csv(path: Path, header: list[str], rows: Iterable[list[str]]) -> tuple[int, int | None, int | None]:
    assert_development_path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent); os.close(fd)
    count = 0; first = last = None
    try:
        with gzip.open(temporary, "wt", encoding="utf-8", newline="", compresslevel=6) as handle:
            writer = csv.writer(handle, lineterminator="\n"); writer.writerow(header)
            for row in rows:
                writer.writerow(row); count += 1
                timestamp = int(row[0]); first = timestamp if first is None else first; last = timestamp
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return count, first, last


def normalize(root: Path) -> dict:
    base = root / ROOT_NAME; metadata = base / "metadata"
    verification = verify_raw_manifest(root)
    manifest = json.loads((metadata / "raw-development-manifest.json").read_text())
    raw_records = [FileRecord(**{**row, "source_inputs": tuple(row["source_inputs"])}) for row in manifest["files"]]
    for record in raw_records:
        path = root / record.path; assert_development_path(path)
        if path.stat().st_size != record.size or sha256_file(path) != record.sha256:
            raise RuntimeError(f"raw checksum mismatch: {record.path}")
    symbols = json.loads((metadata / "roster.snapshot.json").read_text())["symbols"]
    audit = {"duplicates": 0, "conflicting_duplicates": 0, "invalid_rows": {}, "out_of_order": 0, "gaps_over_30m": 0, "gap_intervals": [], "missing_development_histories": []}
    output_records: list[FileRecord] = []; row_counts = {"5m": 0, "funding": 0, **{tf: 0 for tf in TIMEFRAMES}}
    built = utc_now()
    for symbol_index, symbol in enumerate(symbols, 1):
        symbol_raw = [record for record in raw_records if record.symbol == symbol]
        klines = sorted((record for record in symbol_raw if record.datatype == "klines"), key=lambda item: item.start_ms or 0)
        funding = sorted((record for record in symbol_raw if record.datatype == "funding"), key=lambda item: item.start_ms or 0)
        if not klines: audit["missing_development_histories"].append(symbol); continue
        invalid: dict[str, int] = {}
        previous_ts = None; previous_row = None
        clean_rows: list[list[str]] = []
        for record in klines:
            for raw in safe_zip_rows(root / record.path):
                if _is_header(raw): continue
                row, issue = validate_kline(raw)
                if issue: invalid[issue] = invalid.get(issue, 0) + 1; continue
                assert row is not None; timestamp = int(row[0])
                if previous_ts is not None and timestamp < previous_ts:
                    audit["out_of_order"] += 1; continue
                if timestamp == previous_ts:
                    if row == previous_row: audit["duplicates"] += 1
                    else: audit["conflicting_duplicates"] += 1
                    continue
                if previous_ts is not None and timestamp - previous_ts > 6 * BAR_MS:
                    audit["gaps_over_30m"] += 1; audit["gap_intervals"].append({"symbol": symbol, "after_ms": previous_ts, "next_ms": timestamp, "missing_bars": (timestamp-previous_ts)//BAR_MS-1})
                clean_rows.append(row); previous_ts, previous_row = timestamp, row
        if audit["conflicting_duplicates"]:
            raise RuntimeError("conflicting duplicate bars found; fail closed")
        audit["invalid_rows"][symbol] = invalid
        five_path = base / "development" / "normalized" / "klines" / symbol / f"{symbol}-5m.csv.gz"
        count, first, last = _gzip_csv(five_path, KLINE_HEADER, clean_rows); row_counts["5m"] += count
        sources = tuple(record.path for record in klines)
        output_records.append(FileRecord(str(five_path.relative_to(root)), five_path.stat().st_size, sha256_file(five_path), symbol, "klines", "5m", first, None if last is None else last + BAR_MS, sources, built))
        for timeframe, factor in TIMEFRAMES.items():
            def aggregate() -> Iterator[list[str]]:
                bucket: list[list[str]] = []; bucket_start = None
                for row in clean_rows:
                    timestamp = int(row[0]); start = timestamp - timestamp % (factor * BAR_MS)
                    if bucket_start is None or start == bucket_start:
                        bucket.append(row); bucket_start = start; continue
                    if len(bucket) == factor and int(bucket[0][0]) == bucket_start and int(bucket[-1][0]) + BAR_MS == bucket_start + factor * BAR_MS:
                        yield aggregate_bucket(bucket, bucket_start, factor)
                    bucket, bucket_start = [row], start
                if bucket and len(bucket) == factor and int(bucket[0][0]) == bucket_start and int(bucket[-1][0]) + BAR_MS == bucket_start + factor * BAR_MS:
                    yield aggregate_bucket(bucket, bucket_start, factor)
            target = base / "development" / "normalized" / "klines" / symbol / f"{symbol}-{timeframe}.csv.gz"
            n, start, finish = _gzip_csv(target, KLINE_HEADER, aggregate()); row_counts[timeframe] += n
            output_records.append(FileRecord(str(target.relative_to(root)), target.stat().st_size, sha256_file(target), symbol, "klines", timeframe, start, None if finish is None else finish + factor * BAR_MS, (str(five_path.relative_to(root)),), built))
        funding_rows: list[list[str]] = []; seen_funding: dict[int, list[str]] = {}
        for record in funding:
            for raw in safe_zip_rows(root / record.path):
                if _is_header(raw): continue
                row, issue = validate_funding(raw)
                if issue: invalid[f"funding_{issue}"] = invalid.get(f"funding_{issue}", 0) + 1; continue
                assert row is not None; timestamp = int(row[0])
                if timestamp in seen_funding:
                    if seen_funding[timestamp] == row: audit["duplicates"] += 1
                    else: raise RuntimeError(f"conflicting funding duplicate: {symbol} {timestamp}")
                    continue
                seen_funding[timestamp] = row; funding_rows.append(row)
        funding_rows.sort(key=lambda row: int(row[0]))
        funding_path = base / "development" / "normalized" / "funding" / symbol / f"{symbol}-funding.csv.gz"
        n, first_f, last_f = _gzip_csv(funding_path, FUNDING_HEADER, funding_rows); row_counts["funding"] += n
        output_records.append(FileRecord(str(funding_path.relative_to(root)), funding_path.stat().st_size, sha256_file(funding_path), symbol, "funding", None, first_f, None if last_f is None else last_f + 1, tuple(record.path for record in funding), built))
        print(f"normalized {symbol_index}/{len(symbols)} {symbol}: {count} 5m rows", flush=True)
    audit["invalid_row_total"] = sum(sum(values.values()) for values in audit["invalid_rows"].values())
    normalized_manifest = {"protocol_id": PROTOCOL_ID, "partition": "development", "built_at": built, "files": [asdict(item) for item in output_records]}
    atomic_write(metadata / "normalized-development-manifest.json", canonical(normalized_manifest))
    atomic_write(base / "development" / "audit" / "quality.json", canonical(audit))
    return {"verification": verification, "rows": row_counts, "files": len(output_records), "bytes": sum(item.size for item in output_records), **audit}


def aggregate_bucket(rows: list[list[str]], start: int, factor: int) -> list[str]:
    return [str(start), rows[0][1], repr(max(float(row[2]) for row in rows)), repr(min(float(row[3]) for row in rows)), rows[-1][4], repr(sum(float(row[5]) for row in rows)), str(start + factor * BAR_MS - 1), repr(sum(float(row[7]) for row in rows)), str(sum(int(row[8]) for row in rows)), repr(sum(float(row[9]) for row in rows)), repr(sum(float(row[10]) for row in rows))]


def verify_raw_manifest(root: Path) -> dict:
    base = root / ROOT_NAME
    manifest_path = base / "metadata" / "raw-development-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches: list[str] = []
    for record in manifest["files"]:
        path = root / record["path"]
        assert_development_path(path)
        if not path.is_file() or path.stat().st_size != record["size"] or sha256_file(path) != record["sha256"]:
            mismatches.append(record["path"])
    if mismatches:
        raise RuntimeError(f"raw development manifest mismatch: {mismatches[:5]}")
    return {"verified_files": len(manifest["files"]), "mismatches": 0, "manifest_sha256": sha256_file(manifest_path)}


def eligibility(root: Path) -> dict:
    base = root / ROOT_NAME; metadata = base / "metadata"
    symbols = json.loads((metadata / "roster.snapshot.json").read_text())["symbols"]
    summary = {tf: {"decisions": 0, "eligible_10m_25m": 0, "eligible_ge_25m": 0, "ineligible": 0} for tf in ("5m", *TIMEFRAMES)}
    runs: list[dict] = []
    for symbol in symbols:
        path = base / "development" / "normalized" / "klines" / symbol / f"{symbol}-5m.csv.gz"
        if not path.exists(): continue
        first = previous = current_day = None
        current_day_count = 0; current_day_volume = 0.0
        trailing_bars: deque[int] = deque(); long_gaps: deque[int] = deque()
        clean_days: deque[tuple[int, float]] = deque(maxlen=30)
        current = None; run_start = None
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                timestamp = int(row["open_time_ms"]); day = timestamp - timestamp % DAY_MS
                if first is None: first = timestamp; current_day = day
                if day != current_day:
                    if current_day_count == 288:
                        clean_days.append((int(current_day), current_day_volume))
                    else:
                        clean_days.clear()
                    current_day, current_day_count, current_day_volume = day, 0, 0.0
                current_day_count += 1; current_day_volume += float(row["quote_volume"])
                if previous is not None and timestamp - previous > 6 * BAR_MS:
                    long_gaps.append(timestamp)
                trailing_bars.append(timestamp)
                window_start = timestamp - 30 * DAY_MS
                while trailing_bars and trailing_bars[0] < window_start:
                    trailing_bars.popleft()
                while long_gaps and long_gaps[0] <= window_start:
                    long_gaps.popleft()
                age_ok = timestamp - int(first) >= 30 * DAY_MS
                coverage_ok = len(trailing_bars) >= math.ceil(0.99 * 30 * 288)
                gap_ok = not long_gaps and len(clean_days) == 30 and clean_days[0][0] == day - 30 * DAY_MS
                median_volume = statistics.median(value for _, value in clean_days) if gap_ok else None
                state = "ge_25m" if median_volume is not None and median_volume >= 25_000_000 else "10m_25m" if median_volume is not None and median_volume >= 10_000_000 else "ineligible"
                if not (age_ok and coverage_ok and gap_ok): state = "ineligible"
                if state != current:
                    if current is not None: runs.append({"symbol": symbol, "start_ms": run_start, "end_exclusive_ms": timestamp, "state": current})
                    current, run_start = state, timestamp
                previous = timestamp
        if current is not None: runs.append({"symbol": symbol, "start_ms": run_start, "end_exclusive_ms": (previous or 0) + BAR_MS, "state": current})
    for run in runs:
        duration = run["end_exclusive_ms"] - run["start_ms"]
        for tf, factor in {"5m": 1, **TIMEFRAMES}.items():
            step = factor * BAR_MS; decisions = duration // step
            summary[tf]["decisions"] += decisions
            key = "eligible_ge_25m" if run["state"] == "ge_25m" else "eligible_10m_25m" if run["state"] == "10m_25m" else "ineligible"
            summary[tf][key] += decisions
    result = {"protocol_id": PROTOCOL_ID, "rule": "age>=30d; trailing 30d coverage>=99%; 30 complete clean UTC days; median causal daily quote volume", "runs": runs, "summary": summary}
    atomic_write(base / "development" / "audit" / "eligibility.json", canonical(result))
    return {"runs": len(runs), "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=("download", "verify", "normalize", "eligibility", "all")); parser.add_argument("--root", type=Path, default=Path("data")); parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args(); assert_development_path(args.root / ROOT_NAME / "development")
    result = {}
    if args.command in {"download", "all"}: result["download"] = download(args.root, workers=args.workers)
    if args.command == "verify": result["verify"] = verify_raw_manifest(args.root)
    if args.command in {"normalize", "all"}: result["normalize"] = normalize(args.root)
    if args.command in {"eligibility", "all"}: result["eligibility"] = eligibility(args.root)
    print(json.dumps(result, indent=2, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
