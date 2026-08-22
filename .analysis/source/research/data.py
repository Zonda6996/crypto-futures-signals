from __future__ import annotations

import csv
import hashlib
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from calendar import monthrange
from pathlib import Path

from .core import Bar

BASE = "https://data.binance.vision/data/futures/um/monthly"


def months(start_year: int, end_year: int):
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            yield f"{year}-{month:02d}"


def fetch(url: str, retries: int = 4) -> bytes:
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "crypto-edge-research/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError):
            if attempt + 1 == retries:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def cached_zip(url: str, cache_dir: Path) -> tuple[bytes, str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / url.rsplit("/", 1)[-1]
    if not path.exists():
        path.write_bytes(fetch(url))
    payload = path.read_bytes()
    return payload, hashlib.sha256(payload).hexdigest()


def parse_klines(payload: bytes) -> list[Bar]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = archive.namelist()[0]
        rows = csv.reader(io.TextIOWrapper(archive.open(name), encoding="utf-8"))
        result = []
        for row in rows:
            if not row or not row[0].isdigit():
                continue
            result.append(Bar(int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]),
                              float(row[5]), float(row[9])))
        return result


def parse_funding(payload: bytes) -> list[tuple[int, float]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = archive.namelist()[0]
        reader = csv.DictReader(io.TextIOWrapper(archive.open(name), encoding="utf-8"))
        result = []
        for row in reader:
            ts = row.get("calc_time") or row.get("fundingTime")
            rate = row.get("last_funding_rate") or row.get("fundingRate")
            if ts and rate:
                result.append((int(ts), float(rate)))
        return result


def validate_bars(bars: list[Bar]) -> dict:
    duplicates = len(bars) - len({b.ts for b in bars})
    gaps = sum(1 for a, b in zip(bars, bars[1:]) if b.ts - a.ts != 3_600_000)
    invalid = sum(1 for b in bars if b.low > min(b.open, b.close) or b.high < max(b.open, b.close) or b.low > b.high)
    monotonic = all(a.ts < b.ts for a, b in zip(bars, bars[1:]))
    return {"rows": len(bars), "duplicates": duplicates, "gaps": gaps, "invalid_ohlc": invalid, "monotonic": monotonic}


def download_symbol(symbol: str, start_year: int, end_year: int, root: Path) -> tuple[list[Bar], list[tuple[int, float]], dict]:
    bars, funding, files, missing = [], [], [], []
    for period in months(start_year, end_year):
        kline_url = f"{BASE}/klines/{symbol}/1h/{symbol}-1h-{period}.zip"
        try:
            payload, digest = cached_zip(kline_url, root / "cache" / "klines" / symbol)
            parsed = parse_klines(payload)
            bars.extend(parsed)
            files.append({"kind": "klines", "period": period, "sha256": digest, "rows": len(parsed)})
        except urllib.error.HTTPError as error:
            if error.code == 404:
                missing.append({"kind": "klines", "period": period})
            else:
                raise
        funding_url = f"{BASE}/fundingRate/{symbol}/{symbol}-fundingRate-{period}.zip"
        try:
            payload, digest = cached_zip(funding_url, root / "cache" / "funding" / symbol)
            parsed_funding = parse_funding(payload)
            funding.extend(parsed_funding)
            files.append({"kind": "funding", "period": period, "sha256": digest, "rows": len(parsed_funding)})
        except urllib.error.HTTPError as error:
            if error.code == 404:
                missing.append({"kind": "funding", "period": period})
            else:
                raise
    bars = sorted({bar.ts: bar for bar in bars}.values(), key=lambda b: b.ts)
    funding = sorted(set(funding))
    manifest = {
        "symbol": symbol,
        "source": "Binance USD-M public monthly archive",
        "files": files,
        "missing": missing,
        "quality": validate_bars(bars),
        "funding_rows": len(funding),
        "open_interest": {"available": False, "reason": "No point-in-time-safe full-history OI series used in this experiment"},
    }
    return bars, funding, manifest


def save_normalized(symbol: str, bars: list[Bar], funding: list[tuple[int, float]], root: Path) -> None:
    target = root / "normalized"
    target.mkdir(parents=True, exist_ok=True)
    with (target / f"{symbol}-1h.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["open_time", "open", "high", "low", "close", "volume", "taker_buy_volume"])
        for b in bars:
            writer.writerow([b.ts, b.open, b.high, b.low, b.close, b.volume, b.taker_buy_volume])
    (target / f"{symbol}-funding.json").write_text(json.dumps(funding), encoding="utf-8")
