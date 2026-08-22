from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import random
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

PROTOCOL_ID = "ALT-MULTITF-005-PHASE3-FROZEN-1"
DEVELOPMENT_END_MS = 1_767_225_600_000
FEE_PER_SIDE = 0.0005
BASE_SLIPPAGE = 0.0002
STRESS_SLIPPAGE = 0.0005
BASE_PARTICIPATION = 0.005
STRESS_PARTICIPATION = 0.0025
SEED = 20260823
TF_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "1d": 86_400_000}


class ProtocolViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class NativeBar:
    symbol: str
    timeframe: str
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time_ms: int
    quote_volume: float


@dataclass(frozen=True)
class ExchangeFilter:
    tick_size: float
    step_size: float
    min_qty: float
    min_notional: float


@dataclass(frozen=True)
class Fill:
    symbol: str
    decision_time_ms: int
    fill_time_ms: int
    side: str
    quantity: float
    reference_price: float
    fill_price: float
    fee: float
    participation: float


def reject_holdout(*values: object) -> None:
    if any("holdout" in str(value).lower() for value in values):
        raise ProtocolViolation("holdout access is forbidden")


def assert_development_timestamp(timestamp_ms: int) -> None:
    if timestamp_ms >= DEVELOPMENT_END_MS:
        raise ProtocolViolation("timestamp crosses the frozen development boundary")


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def load_frozen_manifest(path: Path | str) -> dict:
    reject_holdout(path)
    raw = Path(path).read_bytes()
    document = json.loads(raw)
    if document.get("protocol_id") != PROTOCOL_ID or not document.get("created_before_pnl"):
        raise ProtocolViolation("unexpected or non-frozen manifest")
    hypotheses = document.get("hypotheses", [])
    counts = {family: sum(row.get("family") == family for row in hypotheses) for family in ("A", "B")}
    if counts != {"A": 3060, "B": 55080}:
        raise ProtocolViolation(f"frozen hypothesis counts changed: {counts}")
    if document.get("development_end_exclusive_ms") != DEVELOPMENT_END_MS:
        raise ProtocolViolation("development boundary changed")
    return document


def load_native_bars(path: Path | str, symbol: str, timeframe: str) -> tuple[NativeBar, ...]:
    reject_holdout(path)
    if timeframe not in TF_MS or not str(path).endswith(f"-{timeframe}.csv.gz"):
        raise ProtocolViolation("timeframe/path mismatch")
    rows: list[NativeBar] = []
    expected = ["open_time_ms", "open", "high", "low", "close", "volume", "close_time_ms", "quote_volume", "trade_count", "taker_buy_base", "taker_buy_quote"]
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        if next(reader, None) != expected:
            raise ProtocolViolation("invalid normalized kline schema")
        previous = -1
        for row in reader:
            opened, closed = int(row[0]), int(row[6])
            if opened >= DEVELOPMENT_END_MS:
                raise ProtocolViolation("normalized bar crosses development boundary")
            if opened <= previous or closed != opened + TF_MS[timeframe] - 1:
                raise ProtocolViolation("non-causal or malformed native bars")
            values = tuple(float(row[index]) for index in (1, 2, 3, 4, 5, 7))
            if not all(math.isfinite(value) and value >= 0 for value in values) or min(values[:4]) <= 0:
                raise ProtocolViolation("invalid OHLCV")
            rows.append(NativeBar(symbol, timeframe, opened, *values[:5], closed, values[5]))
            previous = opened
    return tuple(rows)


def closed_history(bars: Sequence[NativeBar], decision_time_ms: int) -> tuple[NativeBar, ...]:
    assert_development_timestamp(decision_time_ms)
    return tuple(bar for bar in bars if bar.close_time_ms <= decision_time_ms)


def next_open_bar(bars: Sequence[NativeBar], decision_time_ms: int, delay_bars: int = 0) -> NativeBar:
    if delay_bars < 0:
        raise ValueError("delay_bars must be non-negative")
    candidates = [bar for bar in bars if bar.open_time_ms > decision_time_ms]
    if len(candidates) <= delay_bars:
        raise ProtocolViolation("no causal next-open fill exists")
    result = candidates[delay_bars]
    assert_development_timestamp(result.open_time_ms)
    return result


def floor_increment(value: float, increment: float) -> float:
    if value < 0 or increment <= 0:
        raise ValueError("invalid increment rounding input")
    return math.floor((value + 1e-12) / increment) * increment


def adverse_price(price: float, side: str, slippage: float, tick_size: float) -> float:
    if side not in {"buy", "sell"} or price <= 0 or not 0 <= slippage < 1:
        raise ValueError("invalid fill input")
    raw = price * (1 + slippage if side == "buy" else 1 - slippage)
    units = math.ceil(raw / tick_size - 1e-12) if side == "buy" else math.floor(raw / tick_size + 1e-12)
    return units * tick_size


def execute_next_open(
    *, symbol: str, decision_time_ms: int, bars: Sequence[NativeBar], side: str,
    desired_notional: float, filters: ExchangeFilter, trailing_quote_volume: float,
    participation_cap: float = BASE_PARTICIPATION, slippage: float = BASE_SLIPPAGE,
    delay_bars: int = 0,
) -> Fill:
    bar = next_open_bar(bars, decision_time_ms, delay_bars)
    if trailing_quote_volume <= 0 or not 0 < participation_cap <= BASE_PARTICIPATION:
        raise ProtocolViolation("invalid causal liquidity budget")
    price = adverse_price(bar.open, side, slippage, filters.tick_size)
    capped_notional = min(desired_notional, trailing_quote_volume * participation_cap)
    quantity = floor_increment(capped_notional / price, filters.step_size)
    if quantity < filters.min_qty or quantity * price < filters.min_notional:
        raise ProtocolViolation("minQty/minNotional prevents fill")
    actual_notional = quantity * price
    participation = actual_notional / trailing_quote_volume
    if participation > participation_cap + 1e-12:
        raise ProtocolViolation("participation cap breached")
    return Fill(symbol, decision_time_ms, bar.open_time_ms, side, quantity, bar.open, price, actual_notional * FEE_PER_SIDE, participation)


def resolve_stop_take(bar: NativeBar, stop: float | None, take: float | None) -> str | None:
    """Frozen conservative ambiguity rule for a long: stop wins when both touch."""
    if stop is not None and bar.low <= stop:
        return "stop"
    if take is not None and bar.high >= take:
        return "take"
    return None


def rolling_return(equity: Sequence[tuple[int, float]], now_ms: int, days: int = 30) -> float | None:
    current = [value for timestamp, value in equity if timestamp <= now_ms]
    prior = [value for timestamp, value in equity if timestamp <= now_ms - days * TF_MS["1d"]]
    if not current or not prior or prior[-1] <= 0:
        return None
    return current[-1] / prior[-1] - 1


def circuit_breaker(equity: Sequence[tuple[int, float]], now_ms: int) -> bool:
    value = rolling_return(equity, now_ms)
    return value is not None and value <= -0.10


def annualized_metrics(returns: Sequence[float], periods_per_year: float = 365.25) -> dict[str, float]:
    if not returns:
        return {"net_return": 0.0, "sharpe": 0.0, "sortino": 0.0, "max_drawdown": 0.0}
    equity = 1.0
    peak = 1.0
    drawdown = 0.0
    for value in returns:
        if not math.isfinite(value) or value <= -1:
            raise ProtocolViolation("invalid return series")
        equity *= 1 + value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1)
    mean = statistics.fmean(returns)
    sigma = statistics.pstdev(returns)
    downside = math.sqrt(statistics.fmean(min(0.0, value) ** 2 for value in returns))
    return {
        "net_return": equity - 1,
        "sharpe": mean / sigma * math.sqrt(periods_per_year) if sigma else 0.0,
        "sortino": mean / downside * math.sqrt(periods_per_year) if downside else 0.0,
        "max_drawdown": drawdown,
    }


def stationary_bootstrap_indices(length: int, samples: int, block_probability: float, seed: int = SEED) -> list[list[int]]:
    if length <= 0 or samples <= 0 or not 0 < block_probability <= 1:
        raise ValueError("invalid stationary bootstrap arguments")
    rng = random.Random(seed)
    output: list[list[int]] = []
    for _ in range(samples):
        index = rng.randrange(length)
        row = []
        for _ in range(length):
            if rng.random() < block_probability:
                index = rng.randrange(length)
            row.append(index)
            index = (index + 1) % length
        output.append(row)
    return output


def hansen_spa(return_matrix: Sequence[Sequence[float]], samples: int = 10_000, seed: int = SEED) -> dict[str, float | int]:
    if not return_matrix or len({len(row) for row in return_matrix}) != 1:
        raise ValueError("SPA requires a rectangular non-empty return matrix")
    observations = len(return_matrix[0])
    means = [statistics.fmean(row) for row in return_matrix]
    centered = [[value - max(0.0, mean) for value in row] for row, mean in zip(return_matrix, means)]
    observed = max(math.sqrt(observations) * mean / (statistics.pstdev(row) or math.inf) for row, mean in zip(return_matrix, means))
    maxima = []
    for indices in stationary_bootstrap_indices(observations, samples, min(1.0, 1 / math.sqrt(observations)), seed):
        stats = []
        for row in centered:
            sample = [row[index] for index in indices]
            stats.append(math.sqrt(observations) * statistics.fmean(sample) / (statistics.pstdev(sample) or math.inf))
        maxima.append(max(stats))
    p_value = (1 + sum(value >= observed for value in maxima)) / (samples + 1)
    return {"statistic": observed, "p_value": p_value, "resamples": samples, "seed": seed}


def normal_cdf(value: float) -> float:
    return 0.5 * (1 + math.erf(value / math.sqrt(2)))


def deflated_sharpe_probability(sharpe: float, observations: int, trials: int, skew: float = 0.0, kurtosis: float = 3.0) -> float:
    if observations < 2 or trials < 1:
        raise ValueError("invalid DSR arguments")
    euler = 0.5772156649
    z = statistics.NormalDist().inv_cdf(1 - 1 / max(trials, 2))
    z2 = statistics.NormalDist().inv_cdf(1 - 1 / (max(trials, 2) * math.e))
    expected_max = (1 - euler) * z + euler * z2
    denominator = math.sqrt(max(1e-15, (1 - skew * sharpe + (kurtosis - 1) * sharpe * sharpe / 4) / (observations - 1)))
    return normal_cdf((sharpe - expected_max) / denominator)


def momentum(history: Sequence[NativeBar], lookback_days: int, decision_time_ms: int) -> float | None:
    closed = closed_history(history, decision_time_ms)
    cutoff = decision_time_ms - lookback_days * TF_MS["1d"]
    anchors = [bar for bar in closed if bar.close_time_ms <= cutoff]
    if not closed or not anchors or anchors[-1].close <= 0:
        return None
    value = closed[-1].close / anchors[-1].close - 1
    return value if math.isfinite(value) else None


def select_positive_momentum(
    histories: Mapping[str, Sequence[NativeBar]], decision_time_ms: int, lookback_days: int, breadth: str
) -> tuple[tuple[str, float], ...]:
    ranked = sorted(
        ((symbol, value) for symbol, bars in histories.items() if (value := momentum(bars, lookback_days, decision_time_ms)) is not None and value > 0),
        key=lambda row: (-row[1], row[0]),
    )
    if breadth == "top20pct":
        requested = min(len(histories), max(2, math.ceil(0.20 * len(histories))))
    elif breadth.startswith("top") and breadth[3:].isdigit():
        requested = int(breadth[3:])
    else:
        raise ProtocolViolation(f"unknown breadth: {breadth}")
    return tuple(ranked[:requested])


def wilder_atr(history: Sequence[NativeBar], decision_time_ms: int, periods: int = 14) -> float | None:
    closed = closed_history(history, decision_time_ms)
    if len(closed) < periods + 1:
        return None
    true_ranges = [
        max(bar.high - bar.low, abs(bar.high - previous.close), abs(bar.low - previous.close))
        for previous, bar in zip(closed[-periods - 1:-1], closed[-periods:])
    ]
    return statistics.fmean(true_ranges)


def realized_volatility(history: Sequence[NativeBar], decision_time_ms: int, days: int = 30) -> float | None:
    closed = closed_history(history, decision_time_ms)
    cutoff = decision_time_ms - days * TF_MS["1d"]
    window = [bar for bar in closed if bar.close_time_ms > cutoff]
    if len(window) < 2:
        return None
    returns = [math.log(current.close / previous.close) for previous, current in zip(window, window[1:])]
    sigma = statistics.pstdev(returns)
    bars_per_year = 365.0 * TF_MS["1d"] / TF_MS[window[-1].timeframe]
    return sigma * math.sqrt(bars_per_year) if sigma > 0 else None


def portfolio_weights(
    ranked: Sequence[tuple[str, float]], weighting: str, histories: Mapping[str, Sequence[NativeBar]], decision_time_ms: int
) -> dict[str, float]:
    if not ranked:
        return {}
    if weighting == "equal":
        raw = {symbol: 1.0 for symbol, _ in ranked}
    elif weighting == "inverse_vol":
        raw = {symbol: 1 / value for symbol, _ in ranked if (value := realized_volatility(histories[symbol], decision_time_ms))}
    elif weighting == "capped_rank":
        raw = {symbol: float(len(ranked) - index) for index, (symbol, _) in enumerate(ranked)}
    else:
        raise ProtocolViolation(f"unknown weighting: {weighting}")
    total = sum(raw.values())
    if not total:
        return {}
    weights = {symbol: value / total for symbol, value in raw.items()}
    # Frozen 20% symbol cap. Excess remains cash; it is never redistributed above the cap.
    return {symbol: min(0.20, value) for symbol, value in weights.items()}


def family_a_signal(config: Mapping[str, object], histories: Mapping[str, Sequence[NativeBar]], decision_time_ms: int) -> dict[str, float]:
    ranked = select_positive_momentum(histories, decision_time_ms, int(config["lookback_days"]), str(config["breadth"]))
    return portfolio_weights(ranked, str(config["weighting"]), histories, decision_time_ms)


def family_b_entries(config: Mapping[str, object], histories: Mapping[str, Sequence[NativeBar]], decision_time_ms: int) -> tuple[str, ...]:
    ranked = select_positive_momentum(histories, decision_time_ms, int(config["lookback_days"]), "top20pct")
    symbols = [symbol for symbol, _ in ranked]
    if config["entry"] == "next_open":
        return tuple(symbols)
    if config["entry"] != "one_bar_confirmation":
        raise ProtocolViolation("unknown family B entry rule")
    confirmed = []
    for symbol in symbols:
        ranking_history = closed_history(histories[symbol], decision_time_ms)
        confirmation = next_open_bar(histories[symbol], decision_time_ms)
        if ranking_history and confirmation.close > ranking_history[-1].close:
            confirmed.append(symbol)
    return tuple(confirmed)


def percentile_ranks(values: Sequence[float], higher_is_better: bool = True) -> list[float]:
    if not values:
        return []
    ordered = sorted(values)
    low = ordered[max(0, math.ceil(0.05 * len(ordered)) - 1)]
    high = ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]
    clipped = [min(high, max(low, value)) for value in values]
    sorted_clipped = sorted(clipped)
    result = []
    for value in clipped:
        indices = [index for index, candidate in enumerate(sorted_clipped) if candidate == value]
        rank = statistics.fmean(indices) / max(1, len(values) - 1)
        result.append(rank if higher_is_better else 1 - rank)
    return result


def apply_selection_score(rows: list[dict]) -> None:
    specification = (("dsr", True, 0.30), ("sortino", True, 0.20), ("net_return", True, 0.20), ("max_drawdown", True, 0.15), ("turnover", False, 0.10), ("cost_share", False, 0.05))
    for family in ("A", "B"):
        members = [row for row in rows if row.get("family") == family]
        for row in members:
            row["selection_score"] = 0.0
        for metric, higher, weight in specification:
            ranks = percentile_ranks([float(row[metric]) for row in members], higher)
            for row, rank in zip(members, ranks):
                row["selection_score"] += weight * rank


def winner_gate(row: Mapping[str, object]) -> tuple[bool, tuple[str, ...]]:
    checks = {
        "spa": float(row.get("spa_p", 1.0)) < 0.05,
        "dsr": float(row.get("dsr", 0.0)) >= 0.95,
        "positive_return": float(row.get("net_return", 0.0)) > 0,
        "drawdown": float(row.get("max_drawdown", -1.0)) >= -0.30,
        "folds": int(row.get("positive_folds", 0)) >= 4,
        "stress": float(row.get("stress_return", -1.0)) > 0,
        "neighbors": float(row.get("positive_neighbor_share", 0.0)) >= 0.60,
        "liquidity": bool(row.get("liquidity_pass", False)),
        "concentration": bool(row.get("concentration_pass", False)),
    }
    failures = tuple(name for name, passed in checks.items() if not passed)
    return not failures, failures


def outer_folds() -> tuple[tuple[int, int], ...]:
    return tuple((int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000), int(datetime(year + 1, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)) for year in range(2021, 2026))


def audit_manifest(path: Path | str) -> dict:
    document = load_frozen_manifest(path)
    counts = {family: sum(row["family"] == family for row in document["hypotheses"]) for family in ("A", "B")}
    return {"protocol_id": PROTOCOL_ID, "manifest_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "counts": counts, "holdout_opened": False, "outer_folds": outer_folds()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen Phase 4 causal execution and statistics engine")
    parser.add_argument("command", choices=("audit",))
    parser.add_argument("--manifest", type=Path, default=Path("reports/artifacts/altcoin-multitf-005-phase3/frozen-manifest.json"))
    args = parser.parse_args()
    print(json.dumps(audit_manifest(args.manifest), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
