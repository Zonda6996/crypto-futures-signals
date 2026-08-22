from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import numpy as np

from research.altcoin_multitf_phase4 import (
    BASE_PARTICIPATION,
    BASE_SLIPPAGE,
    DEVELOPMENT_END_MS,
    PROTOCOL_ID,
    SEED,
    STRESS_PARTICIPATION,
    STRESS_SLIPPAGE,
    ExchangeFilter,
    NativeBar,
    ProtocolViolation,
    annualized_metrics,
    deflated_sharpe_probability,
    execute_next_open,
    family_a_signal,
    family_b_entries,
    hansen_spa,
    load_frozen_manifest,
    load_native_bars,
    realized_volatility,
    reject_holdout,
    resolve_stop_take,
    wilder_atr,
)

OUTER_FOLDS = tuple((str(year), int(np.datetime64(f"{year}-01-01T00:00:00", "ms").astype(int)), int(np.datetime64(f"{year + 1}-01-01T00:00:00", "ms").astype(int))) for year in range(2021, 2026))
REPORT_VERSION = "ALT-MULTITF-005-PHASE4-1"


@dataclass(frozen=True)
class ReplayScenario:
    name: str = "base"
    slippage: float = BASE_SLIPPAGE
    participation: float = BASE_PARTICIPATION
    delay_bars: int = 0


@dataclass
class ReplayResult:
    config_id: str
    family: str
    returns: list[tuple[int, float]]
    fills: list[dict]
    hard_violations: list[str]
    turnover: float
    costs: float
    funding: float

    def summary(self) -> dict:
        values = [value for _, value in self.returns]
        result = annualized_metrics(values, 365.25)
        result.update({
            "config_id": self.config_id,
            "family": self.family,
            "observations": len(values),
            "turnover": self.turnover,
            "costs": self.costs,
            "funding": self.funding,
            "hard_violation_count": len(self.hard_violations),
        })
        return result


def interval_ms(value: str) -> int:
    unit = value[-1]
    amount = int(value[:-1])
    if amount <= 0 or unit not in {"h", "d"}:
        raise ValueError(f"invalid frozen interval: {value}")
    return amount * (3_600_000 if unit == "h" else 86_400_000)


def load_roster(dataset: Path) -> tuple[str, ...]:
    reject_holdout(dataset)
    document = json.loads((dataset / "metadata/roster.snapshot.json").read_text(encoding="utf-8"))
    symbols = tuple(document["symbols"])
    if document.get("protocol_id") != "ALT-MULTITF-005" or len(symbols) != 40 or len(set(symbols)) != 40:
        raise ProtocolViolation("invalid frozen roster")
    return symbols


def load_histories(dataset: Path, timeframe: str, symbols: Sequence[str] | None = None) -> dict[str, tuple[NativeBar, ...]]:
    reject_holdout(dataset, timeframe)
    selected = tuple(symbols) if symbols is not None else load_roster(dataset)
    histories: dict[str, tuple[NativeBar, ...]] = {}
    for symbol in selected:
        path = dataset / "development/normalized/klines" / symbol / f"{symbol}-{timeframe}.csv.gz"
        histories[symbol] = load_native_bars(path, symbol, timeframe) if path.exists() else ()
    return histories


def decision_times(histories: Mapping[str, Sequence[NativeBar]], cycle: str) -> tuple[int, ...]:
    step = interval_ms(cycle)
    closes = sorted({bar.close_time_ms for bars in histories.values() for bar in bars})
    if not closes:
        return ()
    anchor = closes[0]
    return tuple(timestamp for timestamp in closes if (timestamp - anchor) % step == 0 and timestamp < DEVELOPMENT_END_MS)


def _returns_by_day(events: Iterable[tuple[int, float]]) -> list[tuple[int, float]]:
    totals: dict[int, float] = {}
    for timestamp, value in events:
        day = timestamp - timestamp % 86_400_000
        totals[day] = totals.get(day, 0.0) + value
    return sorted(totals.items())


def _trailing_quote_volume(bars: Sequence[NativeBar], decision: int) -> float:
    start = decision - 86_400_000
    return sum(bar.quote_volume for bar in bars if start < bar.close_time_ms <= decision)


def _default_filter(bars: Sequence[NativeBar]) -> ExchangeFilter:
    prices = [bar.close for bar in bars[:100] if bar.close > 0]
    reference = float(np.median(prices)) if prices else 1.0
    tick = max(10 ** math.floor(math.log10(reference)) * 1e-6, 1e-8)
    return ExchangeFilter(tick_size=tick, step_size=1e-8, min_qty=0.0, min_notional=0.0)


def replay_family_b(config: Mapping[str, object], histories: Mapping[str, Sequence[NativeBar]], scenario: ReplayScenario = ReplayScenario()) -> ReplayResult:
    config_id = str(config["config_id"])
    events: list[tuple[int, float]] = []
    fills: list[dict] = []
    violations: list[str] = []
    turnover = costs = funding = 0.0
    cycle = str(config["ranking_cycle"])
    holding_ms = int(config["time_stop_days"]) * 86_400_000
    for decision in decision_times(histories, cycle):
        symbols = family_b_entries(config, histories, decision)
        if not symbols:
            continue
        allocation = min(0.20, 1.0 / len(symbols))
        for symbol in symbols:
            bars = histories[symbol]
            atr = wilder_atr(bars, decision)
            volatility = realized_volatility(bars, decision)
            if atr is None or volatility is None or volatility <= 0:
                continue
            allocation_scaled = allocation * min(1.0, float(config["volatility_target"]) / volatility)
            try:
                entry = execute_next_open(
                    symbol=symbol,
                    decision_time_ms=decision,
                    bars=bars,
                    side="buy",
                    desired_notional=allocation_scaled,
                    filters=_default_filter(bars),
                    trailing_quote_volume=_trailing_quote_volume(bars, decision),
                    participation_cap=scenario.participation,
                    slippage=scenario.slippage,
                    delay_bars=scenario.delay_bars + (1 if config["entry"] == "one_bar_confirmation" else 0),
                )
            except (ProtocolViolation, ValueError) as exc:
                violations.append(f"{symbol}:{decision}:{exc}")
                continue
            risk = float(config["stop_atr"]) * atr
            stop = entry.fill_price - risk
            take = None if config["take_r"] is None else entry.fill_price + float(config["take_r"]) * risk
            trailing = None if config["trailing_atr"] is None else float(config["trailing_atr"]) * atr
            active = [bar for bar in bars if bar.open_time_ms >= entry.fill_time_ms and bar.open_time_ms < entry.fill_time_ms + holding_ms]
            high_water = entry.fill_price
            exit_bar = active[-1] if active else None
            exit_reason = "time"
            raw_exit = exit_bar.close if exit_bar else entry.raw_price
            for bar in active:
                high_water = max(high_water, bar.high)
                effective_stop = max(stop, high_water - trailing) if trailing is not None else stop
                reason = resolve_stop_take(bar, effective_stop, take)
                if reason:
                    exit_bar, exit_reason = bar, reason
                    raw_exit = effective_stop if reason == "stop" else float(take)
                    break
            if exit_bar is None:
                violations.append(f"{symbol}:{decision}:missing exit")
                continue
            exit_price = raw_exit * (1 - scenario.slippage)
            gross = entry.quantity * (exit_price - entry.fill_price)
            exit_fee = entry.quantity * exit_price * 0.0005
            net = gross - entry.fee - exit_fee
            events.append((exit_bar.close_time_ms, net))
            turnover += entry.quantity * (entry.fill_price + exit_price)
            costs += entry.fee + exit_fee
            fills.append({**asdict(entry), "exit_time_ms": exit_bar.close_time_ms, "exit_price": exit_price, "exit_reason": exit_reason, "net_return": net})
    return ReplayResult(config_id, "B", _returns_by_day(events), fills, violations, turnover, costs, funding)


def fold_metrics(returns: Sequence[tuple[int, float]]) -> list[dict]:
    output: list[dict] = []
    for fold, start, end in OUTER_FOLDS:
        values = [value for timestamp, value in returns if start <= timestamp < end]
        output.append({"fold": fold, **annualized_metrics(values, 365.25)})
    return output


def checkpoint_path(root: Path, family: str, config_id: str) -> Path:
    return root / "checkpoints" / family.lower() / f"{config_id}.json"


def write_checkpoint(path: Path, result: ReplayResult, scenario: ReplayScenario) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"version": REPORT_VERSION, "scenario": asdict(scenario), "summary": result.summary(), "returns": result.returns, "folds": fold_metrics(result.returns), "fills": result.fills, "hard_violations": result.hard_violations}
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(encoded + "\n", encoding="utf-8")
    temporary.replace(path)


def run_family_b(dataset: Path, manifest_path: Path, output: Path, *, limit: int | None = None, resume: bool = True) -> dict:
    manifest = load_frozen_manifest(manifest_path)
    configs = [item for item in manifest["hypotheses"] if item["family"] == "B"]
    if limit is not None:
        configs = configs[:limit]
    grouped: dict[str, list[dict]] = {}
    for config in configs:
        grouped.setdefault(str(config["timeframe"]), []).append(config)
    completed = 0
    for timeframe, tf_configs in grouped.items():
        histories = load_histories(dataset, timeframe)
        for config in tf_configs:
            target = checkpoint_path(output, "B", str(config["config_id"]))
            if resume and target.exists():
                completed += 1
                continue
            result = replay_family_b(config, histories)
            write_checkpoint(target, result, ReplayScenario())
            completed += 1
    status = "COMPLETE" if completed == 55_080 and limit is None else "INCOMPLETE"
    return {"family": "B", "manifest_count": 55_080, "evaluated_count": completed, "status": status}


def collect(output: Path, manifest_path: Path, *, spa_samples: int = 10_000) -> dict:
    manifest = load_frozen_manifest(manifest_path)
    expected = {family: sum(item["family"] == family for item in manifest["hypotheses"]) for family in ("A", "B")}
    leaderboards: dict[str, list[dict]] = {"A": [], "B": []}
    matrices: dict[str, list[list[float]]] = {"A": [], "B": []}
    for family in ("A", "B"):
        for path in sorted((output / "checkpoints" / family.lower()).glob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            summary = document["summary"]
            values = [float(value) for _, value in document["returns"]]
            if values:
                summary["dsr"] = deflated_sharpe_probability(float(summary["sharpe"]), len(values), expected[family])
            else:
                summary["dsr"] = 0.0
            summary["positive_fold_share"] = sum(row["net_return"] > 0 for row in document["folds"]) / len(OUTER_FOLDS)
            leaderboards[family].append(summary)
            matrices[family].append(values)
        leaderboards[family].sort(key=lambda row: (row["dsr"], row["sharpe"], row["net_return"]), reverse=True)
        path = output / f"leaderboard-family-{family.lower()}.csv"
        if leaderboards[family]:
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(leaderboards[family][0])); writer.writeheader(); writer.writerows(leaderboards[family])
    statistics: dict[str, dict] = {}
    for family in ("A", "B"):
        lengths = {len(row) for row in matrices[family]}
        spa = hansen_spa(matrices[family], samples=spa_samples, seed=SEED) if len(lengths) == 1 and lengths != {0} else {"p_value": 1.0, "samples": 0}
        statistics[family] = {"expected": expected[family], "observed": len(leaderboards[family]), "spa": spa, "best_dsr": leaderboards[family][0]["dsr"] if leaderboards[family] else 0.0}
    complete = all(statistics[family]["observed"] == expected[family] for family in ("A", "B"))
    verdict = {"protocol_id": PROTOCOL_ID, "version": REPORT_VERSION, "complete": complete, "families": statistics, "verdict": "NO WINNER", "reason": "Incomplete frozen sweep" if not complete else "No candidate may pass until all frozen robustness gates are materialized."}
    output.mkdir(parents=True, exist_ok=True)
    (output / "statistics.json").write_text(json.dumps(statistics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "verdict.json").write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return verdict


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run-family-b")
    run.add_argument("--dataset", type=Path, required=True); run.add_argument("--manifest", type=Path, required=True); run.add_argument("--output", type=Path, required=True); run.add_argument("--limit", type=int); run.add_argument("--no-resume", action="store_true")
    report = sub.add_parser("collect")
    report.add_argument("--manifest", type=Path, required=True); report.add_argument("--output", type=Path, required=True); report.add_argument("--spa-samples", type=int, default=10_000)
    args = parser.parse_args()
    if args.command == "run-family-b":
        result = run_family_b(args.dataset, args.manifest, args.output, limit=args.limit, resume=not args.no_resume)
    else:
        result = collect(args.output, args.manifest, spa_samples=args.spa_samples)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
