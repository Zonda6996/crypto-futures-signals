from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

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
    apply_selection_score,
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
    winner_gate,
    wilder_atr,
)

DAY_MS = 86_400_000
OUTER_FOLDS = tuple(
    (
        str(year),
        int(np.datetime64(f"{year}-01-01T00:00:00", "ms").astype(int)),
        int(np.datetime64(f"{year + 1}-01-01T00:00:00", "ms").astype(int)),
    )
    for year in range(2021, 2026)
)
REPORT_VERSION = "ALT-MULTITF-005-PHASE4-1"
EXPECTED = {"A": 3_060, "B": 55_080}


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
    funding: float = 0.0

    def summary(self) -> dict:
        values = [value for _, value in self.returns]
        result = annualized_metrics(values, 365.25)
        gross = result["net_return"] + self.costs - self.funding
        result.update(
            {
                "config_id": self.config_id,
                "family": self.family,
                "observations": len(values),
                "gross_return": gross,
                "turnover": self.turnover,
                "costs": self.costs,
                "funding": self.funding,
                "cost_share": self.costs / max(abs(gross), 1e-12),
                "hard_violation_count": len(self.hard_violations),
            }
        )
        return result


def interval_ms(value: str) -> int:
    unit, amount = value[-1], int(value[:-1])
    if amount <= 0 or unit not in {"h", "d"}:
        raise ValueError(f"invalid frozen interval: {value}")
    return amount * (3_600_000 if unit == "h" else DAY_MS)


def load_roster(dataset: Path) -> tuple[str, ...]:
    reject_holdout(dataset)
    path = dataset / "metadata/roster.snapshot.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    symbols = tuple(document.get("symbols", ()))
    if document.get("protocol_id") != "ALT-MULTITF-005" or len(symbols) != 40 or len(set(symbols)) != 40:
        raise ProtocolViolation("invalid frozen roster")
    return symbols


def load_histories(dataset: Path, timeframe: str, symbols: Sequence[str] | None = None) -> dict[str, tuple[NativeBar, ...]]:
    reject_holdout(dataset, timeframe)
    selected = tuple(symbols) if symbols is not None else load_roster(dataset)
    histories: dict[str, tuple[NativeBar, ...]] = {}
    for symbol in selected:
        path = dataset / "development/normalized/klines" / symbol / f"{symbol}-{timeframe}.csv.gz"
        if not path.exists():
            raise ProtocolViolation(f"missing frozen native history: {symbol}-{timeframe}")
        histories[symbol] = load_native_bars(path, symbol, timeframe)
    return histories


def decision_times(histories: Mapping[str, Sequence[NativeBar]], cycle: str) -> tuple[int, ...]:
    step = interval_ms(cycle)
    closes = sorted({bar.close_time_ms for bars in histories.values() for bar in bars})
    if not closes:
        return ()
    anchor = closes[0]
    return tuple(value for value in closes if (value - anchor) % step == 0 and value < DEVELOPMENT_END_MS)


def returns_by_day(events: Iterable[tuple[int, float]]) -> list[tuple[int, float]]:
    totals: dict[int, float] = {}
    for timestamp, value in events:
        day = timestamp - timestamp % DAY_MS
        totals[day] = totals.get(day, 0.0) + value
    return sorted(totals.items())


def trailing_quote_volume(bars: Sequence[NativeBar], decision: int) -> float:
    return sum(bar.quote_volume for bar in bars if decision - DAY_MS < bar.close_time_ms <= decision)


def default_filter(bars: Sequence[NativeBar]) -> ExchangeFilter:
    prices = [bar.close for bar in bars[:100] if bar.close > 0]
    reference = float(np.median(prices)) if prices else 1.0
    tick = max(10 ** math.floor(math.log10(reference)) * 1e-6, 1e-8)
    return ExchangeFilter(tick, 1e-8, 0.0, 0.0)


def exit_long(
    bars: Sequence[NativeBar], entry_time: int, entry_price: float, *, end_time: int,
    stop: float | None = None, take: float | None = None, trailing_distance: float | None = None,
) -> tuple[NativeBar, float, str] | None:
    active = [bar for bar in bars if entry_time <= bar.open_time_ms < end_time]
    if not active:
        return None
    high_water = entry_price
    for bar in active:
        high_water = max(high_water, bar.high)
        effective_stop = max(stop, high_water - trailing_distance) if stop is not None and trailing_distance is not None else stop
        reason = resolve_stop_take(bar, effective_stop, take)
        if reason:
            return bar, float(effective_stop if reason == "stop" else take), reason
    return active[-1], active[-1].close, "time"


def replay_family_a(config: Mapping[str, object], histories: Mapping[str, Sequence[NativeBar]], scenario: ReplayScenario = ReplayScenario()) -> ReplayResult:
    events: list[tuple[int, float]] = []
    fills: list[dict] = []
    violations: list[str] = []
    turnover = costs = 0.0
    cycle = str(config["rebalance"])
    decisions = decision_times(histories, cycle)
    for index, decision in enumerate(decisions):
        weights = family_a_signal(config, histories, decision)
        end = decisions[index + 1] if index + 1 < len(decisions) else min(decision + interval_ms(cycle), DEVELOPMENT_END_MS)
        for symbol, raw_weight in weights.items():
            volatility = realized_volatility(histories[symbol], decision)
            if volatility is None or volatility <= 0:
                continue
            weight = raw_weight * min(1.0, float(config["volatility_target"]) / volatility)
            try:
                entry = execute_next_open(
                    symbol=symbol, decision_time_ms=decision, bars=histories[symbol], side="buy",
                    desired_notional=weight, filters=default_filter(histories[symbol]),
                    trailing_quote_volume=trailing_quote_volume(histories[symbol], decision),
                    participation_cap=scenario.participation, slippage=scenario.slippage,
                    delay_bars=scenario.delay_bars,
                )
            except (ProtocolViolation, ValueError) as exc:
                violations.append(f"{symbol}:{decision}:{exc}")
                continue
            resolved = exit_long(histories[symbol], entry.fill_time_ms, entry.fill_price, end_time=end)
            if resolved is None:
                violations.append(f"{symbol}:{decision}:missing exit")
                continue
            exit_bar, raw_exit, reason = resolved
            exit_price = raw_exit * (1 - scenario.slippage)
            exit_fee = entry.quantity * exit_price * 0.0005
            net = entry.quantity * (exit_price - entry.fill_price) - entry.fee - exit_fee
            events.append((exit_bar.close_time_ms, net))
            turnover += entry.quantity * (entry.fill_price + exit_price)
            costs += entry.fee + exit_fee
            fills.append({**asdict(entry), "exit_time_ms": exit_bar.close_time_ms, "exit_price": exit_price, "exit_reason": reason, "net_return": net})
    return ReplayResult(str(config["config_id"]), "A", returns_by_day(events), fills, violations, turnover, costs)


def replay_family_b(config: Mapping[str, object], histories: Mapping[str, Sequence[NativeBar]], scenario: ReplayScenario = ReplayScenario()) -> ReplayResult:
    events: list[tuple[int, float]] = []
    fills: list[dict] = []
    violations: list[str] = []
    turnover = costs = 0.0
    holding_ms = int(config["time_stop_days"]) * DAY_MS
    for decision in decision_times(histories, str(config["ranking_cycle"])):
        symbols = family_b_entries(config, histories, decision)
        allocation = min(0.20, 1.0 / len(symbols)) if symbols else 0.0
        for symbol in symbols:
            bars = histories[symbol]
            atr, volatility = wilder_atr(bars, decision), realized_volatility(bars, decision)
            if atr is None or volatility is None or volatility <= 0:
                continue
            desired = allocation * min(1.0, float(config["volatility_target"]) / volatility)
            try:
                entry = execute_next_open(
                    symbol=symbol, decision_time_ms=decision, bars=bars, side="buy", desired_notional=desired,
                    filters=default_filter(bars), trailing_quote_volume=trailing_quote_volume(bars, decision),
                    participation_cap=scenario.participation, slippage=scenario.slippage,
                    delay_bars=scenario.delay_bars + (1 if config["entry"] == "one_bar_confirmation" else 0),
                )
            except (ProtocolViolation, ValueError) as exc:
                violations.append(f"{symbol}:{decision}:{exc}")
                continue
            risk = float(config["stop_atr"]) * atr
            take = None if config["take_r"] is None else entry.fill_price + float(config["take_r"]) * risk
            trailing = None if config["trailing_atr"] is None else float(config["trailing_atr"]) * atr
            resolved = exit_long(
                bars, entry.fill_time_ms, entry.fill_price,
                end_time=min(entry.fill_time_ms + holding_ms, DEVELOPMENT_END_MS),
                stop=entry.fill_price - risk, take=take, trailing_distance=trailing,
            )
            if resolved is None:
                violations.append(f"{symbol}:{decision}:missing exit")
                continue
            exit_bar, raw_exit, reason = resolved
            exit_price = raw_exit * (1 - scenario.slippage)
            exit_fee = entry.quantity * exit_price * 0.0005
            net = entry.quantity * (exit_price - entry.fill_price) - entry.fee - exit_fee
            events.append((exit_bar.close_time_ms, net))
            turnover += entry.quantity * (entry.fill_price + exit_price)
            costs += entry.fee + exit_fee
            fills.append({**asdict(entry), "exit_time_ms": exit_bar.close_time_ms, "exit_price": exit_price, "exit_reason": reason, "net_return": net})
    return ReplayResult(str(config["config_id"]), "B", returns_by_day(events), fills, violations, turnover, costs)


def fold_metrics(returns: Sequence[tuple[int, float]]) -> list[dict]:
    return [
        {"fold": fold, **annualized_metrics([value for timestamp, value in returns if start <= timestamp < end], 365.25)}
        for fold, start, end in OUTER_FOLDS
    ]


def checkpoint_path(root: Path, family: str, config_id: str, scenario: str = "base") -> Path:
    return root / "checkpoints" / family.lower() / scenario / f"{config_id}.json"


def write_checkpoint(path: Path, result: ReplayResult, scenario: ReplayScenario) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "version": REPORT_VERSION, "scenario": asdict(scenario), "summary": result.summary(),
        "returns": result.returns, "folds": fold_metrics(result.returns), "fills": result.fills,
        "hard_violations": result.hard_violations,
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(encoded + "\n", encoding="utf-8")
    temporary.replace(path)


def run_family(
    family: str, dataset: Path, manifest_path: Path, output: Path, *, limit: int | None = None,
    resume: bool = True, scenario: ReplayScenario = ReplayScenario(),
) -> dict:
    if family not in EXPECTED:
        raise ValueError("family must be A or B")
    manifest = load_frozen_manifest(manifest_path)
    configs = [item for item in manifest["hypotheses"] if item["family"] == family]
    selected = configs if limit is None else configs[:limit]
    grouped: dict[str, list[dict]] = {}
    for config in selected:
        grouped.setdefault(str(config["timeframe"]), []).append(config)
    completed = 0
    evaluator = replay_family_a if family == "A" else replay_family_b
    for timeframe, tf_configs in sorted(grouped.items()):
        histories = load_histories(dataset, timeframe)
        for config in tf_configs:
            target = checkpoint_path(output, family, str(config["config_id"]), scenario.name)
            if resume and target.exists():
                completed += 1
                continue
            write_checkpoint(target, evaluator(config, histories, scenario), scenario)
            completed += 1
    status = "COMPLETE" if completed == EXPECTED[family] and limit is None and scenario.name == "base" else "INCOMPLETE"
    return {"family": family, "manifest_count": EXPECTED[family], "evaluated_count": completed, "scenario": scenario.name, "status": status}


def aligned_matrix(documents: Sequence[dict]) -> list[list[float]]:
    days = sorted({int(day) for document in documents for day, _ in document["returns"]})
    return [[dict((int(day), float(value)) for day, value in document["returns"]).get(day, 0.0) for day in days] for document in documents]


def concentration(fills: Sequence[dict]) -> dict:
    positive = [max(0.0, float(fill["net_return"])) for fill in fills]
    total = sum(positive)
    symbol_totals: dict[str, float] = {}
    for fill, value in zip(fills, positive):
        symbol_totals[fill["symbol"]] = symbol_totals.get(fill["symbol"], 0.0) + value
    symbol_share = max(symbol_totals.values(), default=0.0) / total if total else 1.0
    top_five_share = sum(sorted(positive, reverse=True)[:5]) / total if total else 1.0
    return {"max_symbol_profit_share": symbol_share, "top_five_trade_profit_share": top_five_share, "pass": symbol_share <= 0.35 and top_five_share <= 0.50}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect(output: Path, manifest_path: Path, *, spa_samples: int = 10_000) -> dict:
    manifest = load_frozen_manifest(manifest_path)
    leaderboards: dict[str, list[dict]] = {"A": [], "B": []}
    family_stats: dict[str, dict] = {}
    for family in ("A", "B"):
        documents = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((output / "checkpoints" / family.lower() / "base").glob("*.json"))]
        matrix = aligned_matrix(documents)
        spa = hansen_spa(matrix, samples=spa_samples, seed=SEED) if matrix and matrix[0] else {"p_value": 1.0, "resamples": 0, "seed": SEED, "statistic": 0.0}
        for document in documents:
            row = dict(document["summary"])
            values = [float(value) for _, value in document["returns"]]
            row["dsr"] = deflated_sharpe_probability(row["sharpe"], len(values), EXPECTED[family]) if len(values) >= 2 else 0.0
            row["spa_p"] = spa["p_value"]
            row["positive_folds"] = sum(fold["net_return"] > 0 for fold in document["folds"])
            row["stress_return"] = -1.0
            row["positive_neighbor_share"] = 0.0
            row["liquidity_pass"] = not document["hard_violations"]
            row["concentration_pass"] = concentration(document["fills"])["pass"]
            leaderboards[family].append(row)
        apply_selection_score(leaderboards[family])
        leaderboards[family].sort(key=lambda row: (row["selection_score"], row["config_id"]), reverse=True)
        target = output / f"leaderboard-family-{family.lower()}.csv"
        if leaderboards[family]:
            with target.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(leaderboards[family][0])); writer.writeheader(); writer.writerows(leaderboards[family])
        family_stats[family] = {
            "expected": EXPECTED[family], "observed": len(documents), "complete": len(documents) == EXPECTED[family],
            "spa": spa, "best_dsr": leaderboards[family][0]["dsr"] if leaderboards[family] else 0.0,
        }
    complete = all(item["complete"] for item in family_stats.values())
    winners: dict[str, dict | None] = {"A": None, "B": None}
    if complete:
        for family in ("A", "B"):
            candidate = leaderboards[family][0]
            passed, failures = winner_gate(candidate)
            winners[family] = {"config_id": candidate["config_id"], "passed": passed, "failures": failures}
    verdict_name = "PASS" if complete and any(item and item["passed"] for item in winners.values()) else "NO WINNER"
    reason = "Incomplete frozen sweep" if not complete else "Frozen selection and mandatory gates evaluated; see family failures."
    verdict = {"protocol_id": PROTOCOL_ID, "version": REPORT_VERSION, "complete": complete, "families": family_stats, "winners": winners, "verdict": verdict_name, "reason": reason, "holdout_opened": False}
    output.mkdir(parents=True, exist_ok=True)
    (output / "statistics.json").write_text(json.dumps(family_stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "verdict.json").write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    inventory = {path.relative_to(output).as_posix(): sha256(path) for path in sorted(output.glob("*.json"))}
    (output / "artifact-hashes.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return verdict


def verify(output: Path, manifest_path: Path) -> dict:
    manifest = load_frozen_manifest(manifest_path)
    counts = {family: len(list((output / "checkpoints" / family.lower() / "base").glob("*.json"))) for family in ("A", "B")}
    ids = {family: {row["config_id"] for row in manifest["hypotheses"] if row["family"] == family} for family in ("A", "B")}
    checkpoint_ids = {family: {path.stem for path in (output / "checkpoints" / family.lower() / "base").glob("*.json")} for family in ("A", "B")}
    result = {"counts": counts, "expected": EXPECTED, "ids_exact": {family: checkpoint_ids[family] == ids[family] for family in ("A", "B")}, "holdout_opened": False}
    result["pass"] = counts == EXPECTED and all(result["ids_exact"].values())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic ALT-MULTITF-005 Phase 4 runner")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--family", choices=("A", "B"), required=True)
    run.add_argument("--dataset", type=Path, required=True); run.add_argument("--manifest", type=Path, required=True); run.add_argument("--output", type=Path, required=True)
    run.add_argument("--limit", type=int); run.add_argument("--no-resume", action="store_true")
    run.add_argument("--scenario", choices=("base", "stress", "delay"), default="base")
    report = sub.add_parser("collect")
    report.add_argument("--manifest", type=Path, required=True); report.add_argument("--output", type=Path, required=True); report.add_argument("--spa-samples", type=int, default=10_000)
    check = sub.add_parser("verify")
    check.add_argument("--manifest", type=Path, required=True); check.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        scenarios = {"base": ReplayScenario(), "stress": ReplayScenario("stress", STRESS_SLIPPAGE, STRESS_PARTICIPATION), "delay": ReplayScenario("delay", BASE_SLIPPAGE, BASE_PARTICIPATION, 1)}
        result = run_family(args.family, args.dataset, args.manifest, args.output, limit=args.limit, resume=not args.no_resume, scenario=scenarios[args.scenario])
    elif args.command == "collect":
        result = collect(args.output, args.manifest, spa_samples=args.spa_samples)
    else:
        result = verify(args.output, args.manifest)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
