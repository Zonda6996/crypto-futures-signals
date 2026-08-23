"""Shared, deterministic baseline types for ALTCOIN_MULTITF_005.

This module contains no network I/O and deliberately keeps the evaluation interval
out of all selection-facing APIs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

UTC = timezone.utc


class Family(str, Enum):
    A = "A"  # trend continuation
    B = "B"  # pullback / mean reversion in regime


@dataclass(frozen=True, order=True)
class Candle:
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if self.close_time_ms <= self.open_time_ms:
            raise ValueError("candle close must follow open")
        if not all(x >= 0 for x in (self.open, self.high, self.low, self.close, self.volume)):
            raise ValueError("negative market data")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("invalid OHLC envelope")


@dataclass(frozen=True)
class ExchangeRules:
    tick_size: float
    step_size: float
    min_qty: float
    min_notional: float
    max_qty: float | None = None


@dataclass(frozen=True)
class StrategyConfig:
    family: Family
    signal_tf_minutes: int
    regime_tf_minutes: int
    fast_window: int
    slow_window: int
    entry_threshold: float
    exit_threshold: float
    stop_atr: float
    take_atr: float
    max_holding_bars: int
    side: str = "both"

    def __post_init__(self) -> None:
        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window must be below slow_window")
        if self.signal_tf_minutes >= self.regime_tf_minutes:
            raise ValueError("regime timeframe must exceed signal timeframe")
        if self.side not in {"both", "long", "short"}:
            raise ValueError("unsupported side")

    @property
    def key(self) -> str:
        payload = json.dumps({**asdict(self), "family": self.family.value}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:20]


@dataclass(frozen=True)
class FrozenIntervals:
    development_start: str
    development_end: str
    evaluation_start: str
    evaluation_end: str

    def __post_init__(self) -> None:
        values = [datetime.fromisoformat(v.replace("Z", "+00:00")) for v in asdict(self).values()]
        if any(v.tzinfo is None for v in values) or not (values[0] < values[1] <= values[2] < values[3]):
            raise ValueError("intervals must be ordered, disjoint and timezone-aware")


def stable_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def deterministic_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def assert_strictly_ordered(candles: Iterable[Candle]) -> tuple[Candle, ...]:
    result = tuple(candles)
    if any(a.close_time_ms >= b.close_time_ms for a, b in zip(result, result[1:])):
        raise ValueError("candles must have unique increasing close times")
    return result


def write_json_atomic(path: Path, payload: Mapping[str, object] | list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
