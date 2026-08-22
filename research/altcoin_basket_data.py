"""Pre-HOLDOUT data layer for exploratory protocol ALT-XSMOM-001-B.

Exploratory fixed-basket evidence with survivorship/selection bias.

This module downloads and audits ONLY pre-HOLDOUT hourly bars and funding for
the frozen 10-symbol basket. Every download, parse and cache read is guarded by
the sealed calendar `< 2026-01-01T00:00:00Z`. Nothing here computes momentum,
returns or PnL.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

HOLDOUT_START_ISO = "2026-01-01T00:00:00Z"
HOLDOUT_START_MS = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

HOUR_MS = 3_600_000
DAY_MS = 86_400_000

MIN_LISTING_AGE_DAYS = 90
MIN_LISTING_AGE_MS = MIN_LISTING_AGE_DAYS * DAY_MS
COVERAGE_WINDOW_DAYS = 30
COVERAGE_WINDOW_MS = COVERAGE_WINDOW_DAYS * DAY_MS
MIN_COVERAGE = 0.95
MIN_CROSS_SECTION = 5

PROTOCOL_ID = "ALT-XSMOM-001-B"
EVIDENCE_LABEL = "exploratory fixed-basket evidence with survivorship/selection bias"

#: Frozen basket in canonical order. Never reorder, extend or substitute.
BASKET: tuple[str, ...] = (
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "AVAXUSDT",
    "DOTUSDT",
)

BASE_URL = "https://data.binance.vision/data/futures/um/monthly"
INTERVAL = "1h"


class HoldoutSealedError(RuntimeError):
    """Raised whenever any operation would touch the sealed HOLDOUT."""


def assert_pre_holdout(*timestamps_ms: int | None) -> None:
    for timestamp in timestamps_ms:
        if timestamp is not None and int(timestamp) >= HOLDOUT_START_MS:
            raise HoldoutSealedError(
                f"sealed HOLDOUT access rejected: {timestamp} >= {HOLDOUT_START_MS} ({HOLDOUT_START_ISO})"
            )


def utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_json(path: Path, value: object) -> str:
    payload = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256_bytes(payload)


@dataclass(frozen=True)
class BasketBar:
    """One closed hourly bar. `ts` is the bar open time in milliseconds."""

    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float


@dataclass(frozen=True)
class FundingEvent:
    ts: int
    rate: float


def pre_holdout_months() -> list[str]:
    """Every month strictly before the HOLDOUT that USD-M archives can contain."""
    periods: list[str] = []
    for year in range(2019, 2026):
        for month in range(1, 13):
            start_ms = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp() * 1000)
            if start_ms >= HOLDOUT_START_MS:
                continue
            periods.append(f"{year}-{month:02d}")
    return periods


def month_bounds_ms(period: str) -> tuple[int, int]:
    year, month = (int(part) for part in period.split("-"))
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + (month == 12), (month % 12) + 1, 1, tzinfo=timezone.utc)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def assert_month_is_pre_holdout(period: str) -> None:
    """A month may only be requested when it lies entirely before the HOLDOUT."""
    start_ms, end_ms = month_bounds_ms(period)
    assert_pre_holdout(start_ms)
    if end_ms > HOLDOUT_START_MS:
        raise HoldoutSealedError(f"month {period} crosses the sealed HOLDOUT boundary")


def fetch_bytes(
    url: str,
    *,
    retries: int = 4,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "altcoin-basket-phase-b/1.0"})
            with opener(request, timeout=90) as response:  # type: ignore[attr-defined]
                return response.read()  # type: ignore[no-any-return]
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError) as error:
            last = error
            time.sleep(2**attempt)
    raise RuntimeError(f"download failed: {url}") from last


def guarded_cached_zip(
    url: str,
    period: str,
    cache_dir: Path,
    *,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> tuple[bytes, str]:
    """Download-or-read a monthly archive, refusing any HOLDOUT month."""
    assert_month_is_pre_holdout(period)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / url.rsplit("/", 1)[-1]
    if not path.exists():
        path.write_bytes(fetch_bytes(url, opener=opener))
    payload = path.read_bytes()
    return payload, sha256_bytes(payload)


def parse_klines(payload: bytes) -> list[BasketBar]:
    """Parse a monthly kline archive, rejecting any row at/after the HOLDOUT."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = archive.namelist()[0]
        rows = csv.reader(io.TextIOWrapper(archive.open(name), encoding="utf-8"))
        parsed: list[BasketBar] = []
        for row in rows:
            if not row or not row[0].strip().lstrip("-").isdigit():
                continue
            ts = int(row[0])
            assert_pre_holdout(ts)
            parsed.append(
                BasketBar(
                    ts=ts,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    quote_volume=float(row[7]),
                )
            )
        return parsed


def parse_funding(payload: bytes) -> list[FundingEvent]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = archive.namelist()[0]
        reader = csv.DictReader(io.TextIOWrapper(archive.open(name), encoding="utf-8"))
        parsed: list[FundingEvent] = []
        for row in reader:
            raw_ts = row.get("calc_time") or row.get("fundingTime")
            raw_rate = row.get("last_funding_rate") or row.get("fundingRate")
            if not raw_ts or not raw_rate:
                continue
            try:
                ts = int(float(raw_ts))
                rate = float(raw_rate)
            except ValueError:
                continue
            assert_pre_holdout(ts)
            parsed.append(FundingEvent(ts, rate))
        return parsed


def audit_series(bars: Sequence[BasketBar]) -> dict:
    """Per-symbol data-quality audit: duplicates, monotonicity, gaps, coverage."""
    timestamps = [bar.ts for bar in bars]
    duplicates = len(timestamps) - len(set(timestamps))
    monotonic = all(a < b for a, b in zip(timestamps, timestamps[1:]))
    off_grid = sum(1 for ts in timestamps if ts % HOUR_MS != 0)
    invalid_ohlc = sum(
        1
        for bar in bars
        if bar.low > min(bar.open, bar.close)
        or bar.high < max(bar.open, bar.close)
        or bar.low > bar.high
        or bar.open <= 0
        or bar.close <= 0
    )
    non_positive_volume = sum(1 for bar in bars if bar.quote_volume < 0)
    if timestamps:
        first, last = min(timestamps), max(timestamps)
        expected = (last - first) // HOUR_MS + 1
        missing = expected - len(set(timestamps))
    else:
        first = last = 0
        expected = missing = 0
    gaps = sum(1 for a, b in zip(timestamps, timestamps[1:]) if b - a != HOUR_MS)
    return {
        "rows": len(bars),
        "first_ts": first,
        "last_ts": last,
        "first_iso": utc_iso(first) if timestamps else None,
        "last_iso": utc_iso(last) if timestamps else None,
        "expected_bars": expected,
        "missing_bars": missing,
        "coverage": (len(set(timestamps)) / expected) if expected else 0.0,
        "duplicates": duplicates,
        "monotonic": monotonic,
        "off_grid_timestamps": off_grid,
        "invalid_ohlc": invalid_ohlc,
        "negative_quote_volume": non_positive_volume,
        "interior_gaps": gaps,
        "holdout_rows": 0,
    }


def download_symbol(
    symbol: str,
    root: Path,
    *,
    periods: Iterable[str] | None = None,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> tuple[list[BasketBar], list[FundingEvent], dict]:
    """Download all pre-HOLDOUT monthly bars and funding for one basket symbol."""
    if symbol not in BASKET:
        raise ValueError(f"symbol outside the frozen basket: {symbol}")
    periods = list(periods if periods is not None else pre_holdout_months())

    bars: list[BasketBar] = []
    funding: list[FundingEvent] = []
    files: list[dict] = []
    missing_klines: list[str] = []
    missing_funding: list[str] = []

    for period in periods:
        kline_url = f"{BASE_URL}/klines/{symbol}/{INTERVAL}/{symbol}-{INTERVAL}-{period}.zip"
        try:
            payload, digest = guarded_cached_zip(
                kline_url, period, root / "cache" / "basket-klines" / symbol, opener=opener
            )
            parsed = parse_klines(payload)
            bars.extend(parsed)
            files.append({"kind": "klines", "period": period, "sha256": digest, "rows": len(parsed)})
        except urllib.error.HTTPError as error:
            if error.code == 404:
                missing_klines.append(period)
            else:
                raise

        funding_url = f"{BASE_URL}/fundingRate/{symbol}/{symbol}-fundingRate-{period}.zip"
        try:
            payload, digest = guarded_cached_zip(
                funding_url, period, root / "cache" / "basket-funding" / symbol, opener=opener
            )
            parsed_funding = parse_funding(payload)
            funding.extend(parsed_funding)
            files.append({"kind": "funding", "period": period, "sha256": digest, "rows": len(parsed_funding)})
        except urllib.error.HTTPError as error:
            if error.code == 404:
                missing_funding.append(period)
            else:
                raise

    bars = sorted({bar.ts: bar for bar in bars}.values(), key=lambda bar: bar.ts)
    funding = sorted({event.ts: event for event in funding}.values(), key=lambda event: event.ts)

    audit = audit_series(bars)
    manifest = {
        "symbol": symbol,
        "interval": INTERVAL,
        "protocol_id": PROTOCOL_ID,
        "evidence_label": EVIDENCE_LABEL,
        "source": "Binance Vision USD-M monthly archives",
        "holdout_start": HOLDOUT_START_ISO,
        "requested_months": len(periods),
        "months_with_klines": sum(1 for row in files if row["kind"] == "klines"),
        "months_with_funding": sum(1 for row in files if row["kind"] == "funding"),
        "missing_kline_months": missing_klines,
        "missing_funding_months": missing_funding,
        "funding_rows": len(funding),
        "quality": audit,
        "files": files,
        "open_interest": {
            "available": False,
            "reason": "no point-in-time-safe complete OI history; recorded as a limitation, not reconstructed",
        },
    }
    return bars, funding, manifest


def first_eligible_ts(bars: Sequence[BasketBar]) -> int | None:
    """Earliest timestamp with 90 days of own history; coverage is checked per decision."""
    if not bars:
        return None
    return bars[0].ts + MIN_LISTING_AGE_MS


def trailing_coverage(timestamps: Sequence[int], decision_ms: int) -> float:
    """Share of expected hourly bars strictly before `decision_ms` in the trailing 30 days."""
    window_start = decision_ms - COVERAGE_WINDOW_MS
    observed = sum(1 for ts in timestamps if window_start <= ts < decision_ms)
    expected = COVERAGE_WINDOW_MS // HOUR_MS
    return observed / expected


def save_normalized(symbol: str, bars: Sequence[BasketBar], funding: Sequence[FundingEvent], root: Path) -> None:
    target = root / "normalized-basket"
    target.mkdir(parents=True, exist_ok=True)
    with (target / f"{symbol}-1h.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["open_time", "open", "high", "low", "close", "volume", "quote_volume"])
        for bar in bars:
            writer.writerow([bar.ts, bar.open, bar.high, bar.low, bar.close, bar.volume, bar.quote_volume])
    (target / f"{symbol}-funding.json").write_text(
        json.dumps([[event.ts, event.rate] for event in funding]), encoding="utf-8"
    )
