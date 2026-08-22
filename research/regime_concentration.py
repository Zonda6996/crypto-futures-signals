from __future__ import annotations

import csv
import heapq
import json
import math
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from .core import Bar, CostModel, Trade, utc_iso
from .data import INTERVAL_MS, download_symbol
from .features import make_features
from .phase1_audit import CANDIDATE
from .search import calibrate_candidate, evaluate_candidate
from .timeframe_robustness import SEALED_TEST_START_TS, scaled_candidate, seal_before_test

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "reports" / "regime-concentration"
YEARS = (2021, 2024)
TIMEFRAMES = {"1h": 1, "30m": 2, "15m": 4}
COST = CostModel(taker_fee_bps=5, half_spread_bps=0, slippage_bps=0)

# The median at bar i is computed from regime observations strictly before i.
MIN_THRESHOLD_OBSERVATIONS = 30


def _past_medians(values: list[float | None], minimum: int = MIN_THRESHOLD_OBSERVATIONS) -> list[float | None]:
    """Return expanding medians using prior values only, never the current value."""
    lower: list[float] = []  # max heap represented by negatives
    upper: list[float] = []
    thresholds: list[float | None] = []
    for value in values:
        count = len(lower) + len(upper)
        if count < minimum:
            thresholds.append(None)
        elif len(lower) > len(upper):
            thresholds.append(-lower[0])
        else:
            thresholds.append((-lower[0] + upper[0]) / 2)
        if value is None or not math.isfinite(value):
            continue
        if not lower or value <= -lower[0]:
            heapq.heappush(lower, -value)
        else:
            heapq.heappush(upper, value)
        if len(lower) > len(upper) + 1:
            heapq.heappush(upper, -heapq.heappop(lower))
        elif len(upper) > len(lower):
            heapq.heappush(lower, -heapq.heappop(upper))
    return thresholds


def causal_btc_regimes(bars: list[Bar], bars_per_hour: int) -> list[dict]:
    trend_window = 90 * 24 * bars_per_hour
    volatility_window = 30 * 24 * bars_per_hour
    log_returns: list[float | None] = [None]
    for previous, current in zip(bars, bars[1:]):
        log_returns.append(math.log(current.close / previous.close))

    trend_values: list[float | None] = [None] * len(bars)
    volatility_values: list[float | None] = [None] * len(bars)
    rolling_sum = 0.0
    rolling_squares = 0.0
    for i, value in enumerate(log_returns):
        if value is not None:
            rolling_sum += value
            rolling_squares += value * value
        expired_i = i - volatility_window
        if expired_i >= 1 and log_returns[expired_i] is not None:
            expired = float(log_returns[expired_i])
            rolling_sum -= expired
            rolling_squares -= expired * expired
        if i >= volatility_window:
            volatility_values[i] = math.sqrt(max(rolling_squares, 0.0))
        if i >= trend_window:
            trend_values[i] = bars[i].close / bars[i - trend_window].close - 1

    trend_thresholds = _past_medians(trend_values)
    volatility_thresholds = _past_medians(volatility_values)
    rows = []
    for trend, volatility, trend_threshold, volatility_threshold in zip(
        trend_values, volatility_values, trend_thresholds, volatility_thresholds
    ):
        ready = all(value is not None for value in (trend, volatility, trend_threshold, volatility_threshold))
        trend_label = "strong" if ready and trend >= trend_threshold else "weak" if ready else None
        volatility_label = "high" if ready and volatility >= volatility_threshold else "low" if ready else None
        rows.append({
            "trend_90d": trend,
            "volatility_30d": volatility,
            "trend_threshold_past_median": trend_threshold,
            "volatility_threshold_past_median": volatility_threshold,
            "trend_regime": trend_label if ready else "insufficient_history",
            "volatility_regime": volatility_label if ready else "insufficient_history",
            "regime": f"{trend_label}_{volatility_label}" if ready else "insufficient_history",
        })
    return rows


def summarize_values(values: list[float]) -> dict:
    ordered = sorted(values, reverse=True)
    total = sum(values)
    summary = {
        "trades": len(values),
        "expectancy_r": mean(values) if values else None,
        "total_r": total,
    }
    for count in (1, 3, 5):
        top = sum(ordered[:count])
        remaining = ordered[count:]
        summary[f"top_{count}_r"] = top
        summary[f"top_{count}_profit_share"] = top / total if total != 0 else None
        summary[f"without_top_{count}_r"] = sum(remaining)
        summary[f"without_top_{count}_expectancy_r"] = mean(remaining) if remaining else None
    return summary


def grouped_summary(rows: list[dict], field: str) -> dict[str, dict]:
    groups: dict[str, list[float]] = {}
    for row in rows:
        label = row.get(field)
        if label is not None:
            groups.setdefault(str(label), []).append(float(row["result_r"]))
    return {label: summarize_values(values) for label, values in sorted(groups.items())}


def leave_one_out(rows: list[dict], field: str) -> dict[str, dict]:
    labels = sorted({str(row[field]) for row in rows if row.get(field) is not None})
    return {
        label: summarize_values([float(row["result_r"]) for row in rows if str(row.get(field)) != label])
        for label in labels
    }


def trade_rows(
    trades: list[Trade], bars: list[Bar], features: list[dict], regimes: list[dict], stop_atr: float
) -> list[dict]:
    index = {bar.ts: i for i, bar in enumerate(bars)}
    rows = []
    for trade in trades:
        signal_i = index[trade.signal_ts]
        regime = regimes[signal_i]
        initial_risk = stop_atr * float(features[signal_i]["atr_24"]) / trade.entry
        rows.append({
            "signal_time": utc_iso(trade.signal_ts),
            "entry_time": utc_iso(trade.entry_ts),
            "exit_time": utc_iso(trade.exit_ts),
            "calendar_year": datetime.fromtimestamp(trade.signal_ts / 1000, tz=timezone.utc).year,
            "trend_regime": regime["trend_regime"],
            "volatility_regime": regime["volatility_regime"],
            "regime": regime["regime"],
            "trend_90d": regime["trend_90d"],
            "volatility_30d": regime["volatility_30d"],
            "trend_threshold_past_median": regime["trend_threshold_past_median"],
            "volatility_threshold_past_median": regime["volatility_threshold_past_median"],
            "exit_reason": trade.exit_reason,
            "net_return": trade.net_return,
            "initial_risk_return": initial_risk,
            "result_r": trade.net_return / initial_risk,
        })
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def analyze_timeframe(interval: str, bars_per_hour: int) -> dict:
    btc_raw, _, btc_manifest = download_symbol("BTCUSDT", *YEARS, DATA, interval=interval)
    eth_raw, funding_raw, eth_manifest = download_symbol("ETHUSDT", *YEARS, DATA, interval=interval)
    btc = seal_before_test(btc_raw)
    eth = seal_before_test(eth_raw)
    funding = [(ts, rate) for ts, rate in funding_raw if ts < SEALED_TEST_START_TS]
    if not btc or not eth or btc[-1].ts + INTERVAL_MS[interval] != SEALED_TEST_START_TS:
        raise RuntimeError("TRAIN+VALIDATION must end exactly at the sealed TEST boundary")
    if [bar.ts for bar in btc] != [bar.ts for bar in eth]:
        raise RuntimeError("BTC and ETH timelines must align before regime labelling")

    candidate = CANDIDATE if interval == "1h" else scaled_candidate(bars_per_hour)
    features = make_features(eth, funding, btc, bars_per_hour=bars_per_hour)
    regimes = causal_btc_regimes(btc, bars_per_hour)
    train_stop = int(len(eth) * 0.75)
    train = list(range(train_stop))
    available = list(range(len(eth)))
    calibration = calibrate_candidate(candidate, features, train)
    # Descriptive concentration over all TRAIN+VALIDATION trades. The candidate and
    # calibration are frozen; this is not presented as a new OOS performance test.
    trades, _ = evaluate_candidate(candidate, eth, features, available, COST, dict(funding), calibration)
    rows = trade_rows(trades, eth, features, regimes, candidate.stop_atr)
    if any(row["regime"] is None for row in rows):
        raise RuntimeError("a trade lacks a causally available BTC regime")
    if any(datetime.fromisoformat(row["signal_time"]).timestamp() * 1000 >= SEALED_TEST_START_TS for row in rows):
        raise RuntimeError("sealed TEST trade entered the analysis")

    result = {
        "interval": interval,
        "bars_per_hour": bars_per_hour,
        "cost_model": asdict(COST),
        "candidate": asdict(candidate),
        "sample": {
            "train_indices": [0, train_stop],
            "validation_indices": [train_stop, len(eth)],
            "evaluated_train_validation_indices": [0, len(eth)],
            "interpretation": "Descriptive full pre-TEST concentration; not a new OOS estimate.",
            "last_included_ts": eth[-1].ts,
            "sealed_test_start_ts": SEALED_TEST_START_TS,
            "test_opened": False,
        },
        "regime_method": {
            "trend": "trailing 90-day BTC return",
            "volatility": "trailing 30-day BTC realized volatility from log returns",
            "thresholds": "expanding median of prior valid observations, excluding the current bar",
            "minimum_prior_observations": MIN_THRESHOLD_OBSERVATIONS,
        },
        "overall": summarize_values([float(row["result_r"]) for row in rows]),
        "by_calendar_year": grouped_summary(rows, "calendar_year"),
        "by_regime": grouped_summary(rows, "regime"),
        "leave_one_year_out": leave_one_out(rows, "calendar_year"),
        "leave_one_regime_out": leave_one_out(rows, "regime"),
        "artifact_integrity": {
            "trade_rows": len(rows),
            "all_trade_timestamps_before_test": True,
            "all_trades_have_regime": True,
            "btc_quality": btc_manifest["quality"],
            "eth_quality": eth_manifest["quality"],
        },
    }
    write_csv(OUTPUT / f"trades-{interval}.csv", rows)
    (OUTPUT / f"results-{interval}.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    return result


def markdown_report(results: dict[str, dict]) -> str:
    lines = [
        "# Frozen ETHUSDT — regime and profit concentration",
        "",
        "Статус: отдельная дополнительная диагностика; результаты не относятся к Phase 2–4.",
        "",
        "Закрытый TEST: **не открыт**. Загружены только 2021–2024 годы; данные с `2025-01-01` не загружались и не анализировались.",
        "",
        "## Метод",
        "",
        "Frozen-правила без переоптимизации применены ко всем сделкам TRAIN+VALIDATION для 1h, M30 и M15 при 0,10% round trip. Это описательный concentration-срез, а не новая OOS-оценка. Режим сделки определяется на timestamp сигнала: trend — trailing 90-day BTC return, volatility — trailing 30-day realized volatility. Оба regime-порога — expanding median только прошлых валидных значений, без текущего наблюдения.",
        "",
        "## Общая концентрация",
        "",
        "| TF | Trades | Total R | Top-1 share | Top-3 share | Top-5 share | Без top-1 | Без top-3 | Без top-5 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for interval, result in results.items():
        item = result["overall"]
        percentage = lambda value: "n/a" if value is None else f"{100 * value:.1f}%"
        lines.append(
            f"| {interval} | {item['trades']} | {item['total_r']:+.3f} | "
            f"{percentage(item['top_1_profit_share'])} | {percentage(item['top_3_profit_share'])} | "
            f"{percentage(item['top_5_profit_share'])} | {item['without_top_1_r']:+.3f} | "
            f"{item['without_top_3_r']:+.3f} | {item['without_top_5_r']:+.3f} |"
        )
    lines.extend(["", "## Календарные годы и режимы", ""])
    for interval, result in results.items():
        lines.extend([f"### {interval}", "", "Годы:", ""])
        for label, item in result["by_calendar_year"].items():
            lines.append(f"- {label}: {item['trades']} сделок, `{item['total_r']:+.3f}R`.")
        lines.extend(["", "BTC regimes:", ""])
        for label, item in result["by_regime"].items():
            lines.append(f"- `{label}`: {item['trades']} сделок, `{item['total_r']:+.3f}R`.")
        lines.append("")
    lines.extend([
        "## Leave-one-out",
        "",
        "Полные leave-one-year-out и leave-one-regime-out таблицы находятся в отдельных JSON. Они являются диагностикой концентрации, а не основанием менять frozen-параметры.",
        "",
        "## Ограничение",
        "",
        "Режимы размечены каузально, но их определения выбраны для диагностики после наблюдения слабости top-5. Анализ не подтверждает edge и не разрешает открытие TEST.",
        "",
    ])
    return "\n".join(lines)


def run() -> dict:
    results = {interval: analyze_timeframe(interval, factor) for interval, factor in TIMEFRAMES.items()}
    report = {
        "study": "frozen-regime-profit-concentration",
        "separate_from_phases_2_to_4": True,
        "test_opened": False,
        "sealed_test_start_ts": SEALED_TEST_START_TS,
        "results": results,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "results.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (ROOT / "reports" / "REGIME_CONCENTRATION.md").write_text(markdown_report(results), encoding="utf-8")
    return report


if __name__ == "__main__":
    output = run()
    print(json.dumps({key: value["overall"] for key, value in output["results"].items()}, indent=2))
