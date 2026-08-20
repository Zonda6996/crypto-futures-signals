from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass
from math import exp, sqrt
from statistics import mean
from typing import Sequence

from .core import Bar, CostModel, ExitRules, Trade, assert_selection_indices, chronological_splits, metrics, simulate_trade


@dataclass(frozen=True)
class Candidate:
    feature: str
    side: int
    threshold_q: float
    horizon: int
    regime: str
    volatility: str
    stop_atr: float
    take_atr: float


def quantile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, max(0, int(q * (len(ordered) - 1))))]


def candidate_grid() -> list[Candidate]:
    return [Candidate(feature, side, q, horizon, regime, vol, stop, take)
            for feature in ("ret_4", "ret_24", "reversal_1", "breakout_48", "vwap_distance_24", "taker_imbalance_24", "relative_strength_24")
            for side in (-1, 1) for q in (0.65, 0.75, 0.85) for horizon in (4, 12, 24)
            for regime in ("all", "bull", "bear", "range") for vol in ("all", "low", "high")
            for stop, take in ((1.5, 2.0), (2.0, 3.0))]


def empirical_p_value(returns: Sequence[float]) -> float:
    if len(returns) < 2:
        return 1.0
    avg = mean(returns)
    variance = sum((x - avg) ** 2 for x in returns) / (len(returns) - 1)
    if variance <= 0:
        return 1.0 if avg <= 0 else 0.0
    z = avg / sqrt(variance / len(returns))
    # one-sided normal approximation without scipy
    return 0.5 * (1 - _erf(z / sqrt(2)))


def _erf(x: float) -> float:
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1 / (1 + 0.3275911 * x)
    poly = (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t
    return sign * (1 - poly * exp(-x * x))


def bootstrap_ci(values: Sequence[float], seed: int = 6996, samples: int = 1000) -> list[float | None]:
    if len(values) < 10:
        return [None, None]
    rng = random.Random(seed)
    means = sorted(mean(rng.choices(values, k=len(values))) for _ in range(samples))
    return [means[int(samples * 0.025)], means[int(samples * 0.975)]]


def evaluate_candidate(candidate: Candidate, bars: Sequence[Bar], features: Sequence[dict], indices: Sequence[int], costs: CostModel,
                       funding_by_ts: dict[int, float]) -> tuple[list[Trade], dict]:
    usable = [i for i in indices if features[i].get("ready") and features[i].get(candidate.feature) is not None]
    feature_values = [float(features[i][candidate.feature]) for i in usable]
    threshold = quantile(feature_values, candidate.threshold_q if candidate.side == 1 else 1 - candidate.threshold_q)
    rv_values = [float(features[i]["rv_24"]) for i in usable]
    rv_median = quantile(rv_values, 0.5)
    selected, last_exit = [], -1
    for i in usable:
        value = float(features[i][candidate.feature])
        direction_ok = value >= threshold if candidate.side == 1 else value <= threshold
        regime_ok = candidate.regime == "all" or features[i]["btc_regime"] == candidate.regime
        vol_ok = candidate.volatility == "all" or (candidate.volatility == "high") == (float(features[i]["rv_24"]) >= rv_median)
        if direction_ok and regime_ok and vol_ok and i > last_exit:
            trade = simulate_trade(bars, i, candidate.side, float(features[i]["atr_24"]),
                                   ExitRules(candidate.horizon, candidate.stop_atr, candidate.take_atr), costs, funding_by_ts)
            if trade:
                selected.append(trade)
                last_exit = i + trade.bars_held
    result = metrics(selected)
    values = [t.net_return for t in selected]
    result.update({"threshold": threshold, "expectancy_ci95": bootstrap_ci(values), "p_value": empirical_p_value(values)})
    return selected, result


def benjamini_hochberg(records: list[dict], alpha: float = 0.05) -> None:
    ordered = sorted(enumerate(records), key=lambda item: item[1]["validation"]["p_value"])
    accepted_rank = 0
    for rank, (_, record) in enumerate(ordered, 1):
        if record["validation"]["p_value"] <= alpha * rank / max(1, len(records)):
            accepted_rank = rank
    accepted = {index for _, (index, _) in enumerate(ordered[:accepted_rank])}
    for index, record in enumerate(records):
        record["fdr_significant"] = index in accepted


def search(bars: Sequence[Bar], features: Sequence[dict], funding: Sequence[tuple[int, float]], costs: CostModel, limit: int | None = None) -> dict:
    splits = chronological_splits(len(bars))
    train_indices, validation_indices = list(splits["train"]), list(splits["validation"])
    assert_selection_indices(train_indices + validation_indices, splits)
    funding_map = dict(funding)
    records = []
    grid = candidate_grid()[:limit] if limit else candidate_grid()
    for candidate in grid:
        _, train_result = evaluate_candidate(candidate, bars, features, train_indices, costs, funding_map)
        _, validation_result = evaluate_candidate(candidate, bars, features, validation_indices, costs, funding_map)
        records.append({"candidate": asdict(candidate), "train": train_result, "validation": validation_result})
    benjamini_hochberg(records)
    eligible = [r for r in records if r["fdr_significant"] and r["validation"]["trades"] >= 30
                and (r["validation"]["expectancy_ci95"][0] or -1) > 0 and (r["train"]["expectancy"] or -1) > 0]
    eligible.sort(key=lambda r: (r["validation"]["expectancy_ci95"][0], r["validation"]["expectancy"]), reverse=True)
    return {"candidates_tested": len(records), "eligible": len(eligible), "selected": eligible[0] if eligible else None,
            "top_validation": sorted(records, key=lambda r: r["validation"]["expectancy"] or -999, reverse=True)[:20],
            "split_boundaries": {key: [value.start, value.stop] for key, value in splits.items()}}


def robustness(candidate: Candidate, bars: Sequence[Bar], features: Sequence[dict], indices: Sequence[int], funding: Sequence[tuple[int, float]]) -> dict:
    scenarios = {}
    for name, costs, delay in (
        ("base", CostModel(), 1),
        ("costs_150pct", CostModel(7.5, 1.5, 3.0), 1),
        ("costs_200pct", CostModel(10, 2, 4), 1),
    ):
        trades, result = evaluate_candidate(candidate, bars, features, indices, costs, dict(funding))
        scenarios[name] = result
        if name == "base" and trades:
            trimmed5 = sorted((t.net_return for t in trades), reverse=True)[5:]
            trimmed10 = sorted((t.net_return for t in trades), reverse=True)[10:]
            scenarios["remove_best_5"] = {"trades": len(trimmed5), "expectancy": mean(trimmed5) if trimmed5 else None}
            scenarios["remove_best_10"] = {"trades": len(trimmed10), "expectancy": mean(trimmed10) if trimmed10 else None}
    return scenarios


def config_hash(candidate: Candidate) -> str:
    return hashlib.sha256(json.dumps(asdict(candidate), sort_keys=True).encode()).hexdigest()
