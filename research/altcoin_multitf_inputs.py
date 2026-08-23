"""Composite immutable input handling for ALTCOIN_MULTITF_005 Phase 4 Part 2.

Responsibilities:
- verify the primary archive and supplement by SHA-256 before any use;
- extract both archives into a merged tree with strict no-overwrite semantics;
- build/check a deterministic composite input manifest binding every frozen input;
- load per-symbol causal datasets (candles per timeframe, funding, exchange rules).

Evaluation-interval data is never loaded; paths containing it are rejected.
The evaluation interval stays sealed: no file from it is read, hashed as a working
input, or analysed at any stage of development selection.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path

from research.altcoin_multitf_phase3 import Candle, ExchangeRules
from research.altcoin_multitf_phase4 import FundingEvent
from research.altcoin_multitf_phase4_fast import CompactSeries, build_compact

PROTOCOL_ID = "ALT-MULTITF-005"
PRIMARY_ROOT = "altcoin-multitf-005"
SUPPLEMENT_ROOT = "altcoin-multitf-005-supplement"
DEV_START_MS = 1_609_459_200_000
DEV_END_EXCLUSIVE_MS = 1_704_067_200_000
BAR_MS = 300_000
TIMEFRAME_FILES = {5: "5m", 15: "15m", 30: "30m", 60: "1h", 120: "2h", 240: "4h", 1440: "1d", 10080: "1w"}
UNIVERSE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT")
SUPPLEMENT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "DOTUSDT")

PRIMARY_ARCHIVE_SHA256 = "665ac7b7cb6057b3511d60d08bee144fe747ec205cfff9f8494d94826a83743d"
PRIMARY_ARCHIVE_SIZE = 1_541_152_490
PRIMARY_SOURCE_COMMIT = "f9ee53d7d0009b573bbeba0811b70712e49de3d2"
PRIMARY_CHECKPOINT_CONFIG_HASH = "b63129f81b0bfcff4283b53a67aea2644e96016c4db5818d06b8899f8aee1474"
SUPPLEMENT_ARCHIVE_SHA256 = "a753585a11beb7bad74f9262920324fe8315a681b6dd108db072790bad47bd5b"
SUPPLEMENT_ARCHIVE_SIZE = 113_083_086


class InputError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_development_path(path: Path) -> None:
    lowered = {part.lower() for part in path.parts}
    if {"sealed-holdout", "holdout", "evaluation"} & lowered:
        raise InputError(f"non-development path rejected: {path}")


def verify_archive(path: Path, expected_sha256: str, expected_size: int) -> dict:
    if not path.is_file():
        raise InputError(f"missing archive: {path}")
    size = path.stat().st_size
    if size != expected_size:
        raise InputError(f"archive size mismatch for {path.name}: {size} != {expected_size}")
    digest = sha256_file(path)
    if digest != expected_sha256:
        raise InputError(f"archive sha256 mismatch for {path.name}: {digest} != {expected_sha256}")
    return {"path": path.name, "size": size, "sha256": digest}


def _safe_extract(archive_path: Path, destination: Path) -> list[str]:
    """Extract a tar.gz into destination refusing any overwrite of existing files."""
    extracted: list[str] = []
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            name = member.name
            pure = Path(name)
            if pure.is_absolute() or ".." in pure.parts:
                raise InputError(f"unsafe archive member: {name}")
            if not (name.startswith(f"./{PRIMARY_ROOT}") or name.startswith(f"./{SUPPLEMENT_ROOT}") or name.startswith(PRIMARY_ROOT) or name.startswith(SUPPLEMENT_ROOT)):
                raise InputError(f"unexpected archive root member: {name}")
            target = destination / name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise InputError(f"unsupported archive member type: {name}")
            if target.exists():
                existing = sha256_file(target)
                incoming = hashlib.sha256()
                stream = archive.extractfile(member)
                if stream is None:
                    raise InputError(f"unreadable archive member: {name}")
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    incoming.update(chunk)
                if existing != incoming.hexdigest():
                    raise InputError(f"input conflict on {name}; merging refuses overwrites")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            if stream is None:
                raise InputError(f"unreadable archive member: {name}")
            with target.open("wb") as handle:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    handle.write(chunk)
            extracted.append(name)
    return extracted


@dataclass(frozen=True)
class SymbolDataset:
    symbol: str
    execution_bars: tuple[Candle, ...]
    signal_bars_by_tf: dict[int, tuple[Candle, ...]]
    regime_bars: tuple[Candle, ...]
    funding: tuple[FundingEvent, ...]
    rules: ExchangeRules


class CompositeInputs:
    """Verified merged view of the primary archive plus the supplement."""

    def __init__(self, merged_root: Path, rules: dict[str, ExchangeRules]):
        self.merged_root = merged_root.resolve()
        self.rules = rules
        self.primary_base = self.merged_root / PRIMARY_ROOT
        self.supplement_base = self.merged_root / SUPPLEMENT_ROOT

    def base_for(self, symbol: str) -> Path:
        if symbol in SUPPLEMENT_SYMBOLS:
            return self.supplement_base
        return self.primary_base

    def klines_path(self, symbol: str, tf_minutes: int) -> Path:
        tf_name = TIMEFRAME_FILES[tf_minutes]
        return self.base_for(symbol) / "development" / "normalized" / "klines" / symbol / f"{symbol}-{tf_name}.csv.gz"

    def funding_path(self, symbol: str) -> Path:
        return self.base_for(symbol) / "development" / "normalized" / "funding" / symbol / f"{symbol}-funding.csv.gz"

    def load_candles(self, symbol: str, tf_minutes: int) -> tuple[Candle, ...]:
        path = self.klines_path(symbol, tf_minutes)
        assert_development_path(path)
        if not path.is_file():
            raise InputError(f"missing normalized klines for {symbol} {tf_minutes}m: {path}")
        candles: list[Candle] = []
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                open_ms = int(row["open_time_ms"])
                close_ms = int(row["close_time_ms"])
                if open_ms < DEV_START_MS or close_ms >= DEV_END_EXCLUSIVE_MS:
                    continue
                candle = Candle(
                    open_ms,
                    close_ms,
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row["volume"]),
                )
                candles.append(candle)
        if not candles:
            raise InputError(f"empty klines for {symbol} {tf_minutes}m")
        if candles[0].open_time_ms != DEV_START_MS or candles[-1].close_time_ms < DEV_END_EXCLUSIVE_MS - BAR_MS:
            raise InputError(
                f"incomplete development coverage for {symbol} {tf_minutes}m after clipping: "
                f"[{candles[0].open_time_ms}, {candles[-1].close_time_ms}]"
            )
        return tuple(candles)

    def load_compact_series(self, symbol: str, tf_minutes: int) -> CompactSeries:
        """Memory-light load straight into column arrays, clipped to the frozen
        development interval. Bars outside it are never read into memory, which
        keeps the evaluation interval sealed."""
        path = self.klines_path(symbol, tf_minutes)
        assert_development_path(path)
        if not path.is_file():
            raise InputError(f"missing normalized klines for {symbol} {tf_minutes}m: {path}")
        bars = []
        first_open = None
        last_close = None
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                open_ms = int(row["open_time_ms"])
                close_ms = int(row["close_time_ms"])
                if open_ms < DEV_START_MS or close_ms >= DEV_END_EXCLUSIVE_MS:
                    continue
                bars.append(
                    Candle(
                        open_ms,
                        close_ms,
                        float(row["open"]),
                        float(row["high"]),
                        float(row["low"]),
                        float(row["close"]),
                        float(row["volume"]),
                    )
                )
                if first_open is None:
                    first_open = open_ms
                last_close = close_ms
        if not bars:
            raise InputError(f"empty klines for {symbol} {tf_minutes}m")
        if first_open != DEV_START_MS or last_close < DEV_END_EXCLUSIVE_MS - BAR_MS:
            raise InputError(
                f"incomplete development coverage for {symbol} {tf_minutes}m after clipping: "
                f"[{first_open}, {last_close}]"
            )
        return build_compact(bars)

    def load_funding(self, symbol: str) -> tuple[FundingEvent, ...]:
        path = self.funding_path(symbol)
        assert_development_path(path)
        if not path.is_file():
            raise InputError(f"missing funding history for {symbol}: {path}")
        events: list[FundingEvent] = []
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                timestamp = int(row["funding_time_ms"])
                if timestamp < DEV_START_MS or timestamp >= DEV_END_EXCLUSIVE_MS:
                    continue
                rate_text = row.get("funding_rate", "")
                if not rate_text:
                    continue
                events.append(FundingEvent(timestamp, float(rate_text)))
        return tuple(events)

    def dataset_for(self, symbol: str, signal_tfs: tuple[int, ...] = (15, 60)) -> SymbolDataset:
        execution = self.load_candles(symbol, 5)
        regime = self.load_candles(symbol, 240)
        signals = {tf: self.load_candles(symbol, tf) for tf in signal_tfs}
        funding = self.load_funding(symbol)
        rule = self.rules.get(symbol)
        if rule is None:
            raise InputError(f"no exchange rules for {symbol}")
        return SymbolDataset(symbol, execution, signals, regime, funding, rule)

    @staticmethod
    def load_rules(merged_root: Path) -> dict[str, ExchangeRules]:
        path = Path(merged_root).resolve() / SUPPLEMENT_ROOT / "metadata" / "supplement.exchange-rules.json"
        payload = json.loads(path.read_text())
        rules: dict[str, ExchangeRules] = {}
        for symbol, values in sorted(payload.items()):
            max_qty = values.get("max_qty")
            rules[symbol] = ExchangeRules(
                float(values["tick_size"]),
                float(values["step_size"]),
                float(values["min_qty"]),
                float(values["min_notional"]),
                None if max_qty is None else float(max_qty),
            )
        missing = [symbol for symbol in UNIVERSE_SYMBOLS if symbol not in rules]
        if missing:
            raise InputError(f"rules missing universe symbols: {missing}")
        return rules


def composite_manifest(
    protocol_doc_path: Path,
    repo_commit: str,
    primary_path: Path,
    supplement_path: Path,
    inputs_verified: bool,
) -> dict:
    protocol_hash = sha256_file(protocol_doc_path)
    return {
        "protocol_id": PROTOCOL_ID,
        "repo_source_commit": repo_commit,
        "frozen_protocol_document": protocol_doc_path.name,
        "frozen_protocol_sha256": protocol_hash,
        "development_interval_utc": ["2021-01-01T00:00:00Z", "2023-12-31T23:59:59Z"],
        "evaluation_interval_utc": ["2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"],
        "evaluation_sealed": True,
        "universe_used": list(UNIVERSE_SYMBOLS),
        "primary_archive": {
            "revision": "ALT-MULTITF-005",
            "source_commit": PRIMARY_SOURCE_COMMIT,
            "url_pathname": f"{PROTOCOL_ID.lower()}/{PRIMARY_ARCHIVE_SHA256}.tar.gz",
            "size": PRIMARY_ARCHIVE_SIZE,
            "sha256": PRIMARY_ARCHIVE_SHA256,
            "checkpoint_config_hash": PRIMARY_CHECKPOINT_CONFIG_HASH,
        },
        "supplement_archive": {
            "root_name": SUPPLEMENT_ROOT,
            "symbols_added": list(SUPPLEMENT_SYMBOLS),
            "size": SUPPLEMENT_ARCHIVE_SIZE,
            "sha256": SUPPLEMENT_ARCHIVE_SHA256,
            "sources": {
                "exchange_info": "https://www.binance.com/fapi/v1/exchangeInfo",
                "klines_pattern": "https://data.binance.vision/data/futures/um/monthly/klines/{SYMBOL}/5m/{SYMBOL}-5m-YYYY-MM.zip",
                "funding_pattern": "https://data.binance.vision/data/futures/um/monthly/fundingRate/{SYMBOL}/{SYMBOL}-fundingRate-YYYY-MM.zip",
            },
        },
        "merge_policy": "supplement only adds files; conflicts abort; no overwrites",
        "inputs_verified": inputs_verified,
        "ambiguous_hash_note": (
            "sha256:02b03ddf3e73f84e6c53a40b3e910058e5b3f4d3861716a7dfc25a24de692953 "
            "from the Part 2 assignment matches no artifact in this run (not the primary "
            "archive, its raw manifest, nor the build config hash); it is recorded here "
            "verbatim and is NOT used as an input hash."
        ),
    }
