from __future__ import annotations

import html
import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .core import CostModel, chronological_splits, metrics
from .data import download_symbol, save_normalized
from .features import FEATURE_CATALOG, make_features
from .search import Calibration, Candidate, config_hash, evaluate_candidate, robustness, search

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
PUBLIC = ROOT / "public" / "reports"
EXPERIMENT = "binance-btc-eth-1h-v1"
YEARS = (2021, 2025)
SYMBOLS = ("BTCUSDT", "ETHUSDT")


def git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def write_html(path: Path, report: dict) -> None:
    """Write a dependency-free, immutable human-readable report artifact."""
    verdict = html.escape(str(report["verdict"]))
    reason = html.escape(str(report["reason"]))
    scope = report["scope"]
    selection = report["selection"]
    rows = sum(item["quality"]["rows"] for item in report["data_quality"].values())
    tested = sum(item["candidates_tested"] for item in selection.values()) if not report["test_opened"] else selection["candidates_tested"]
    test_state = "OPENED ONCE" if report["test_opened"] else "SEALED"
    document = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(str(report['experiment_id']))} — {verdict}</title>
<style>body{{margin:0;background:#0a0d10;color:#eef2f3;font:16px/1.6 system-ui,sans-serif}}main{{max-width:920px;margin:auto;padding:48px 24px}}code,.label{{font-family:ui-monospace,monospace}}.label{{color:#6ee7df;font-size:12px;letter-spacing:.14em;text-transform:uppercase}}h1{{font-size:clamp(36px,7vw,72px);line-height:1.05;margin:.25em 0}}.verdict{{color:#ff8075}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));border-block:1px solid #30383d;margin:36px 0}}.stat{{padding:22px 0}}.value{{font-size:28px;font-weight:650}}p{{max-width:720px;color:#aab4b9}}a{{color:#6ee7df}}</style></head>
<body><main><div class="label">Quant research / immutable artifact</div><h1>Edge не подтверждён</h1><strong class="verdict">{verdict}</strong><p>{reason}</p>
<section class="grid"><div class="stat"><div class="label">Гипотез</div><div class="value">{tested:,}</div></div><div class="stat"><div class="label">Баров</div><div class="value">{rows:,}</div></div><div class="stat"><div class="label">TEST</div><div class="value">{test_state}</div></div></section>
<h2>Что проверялось</h2><p>{html.escape(', '.join(scope['symbols']))}, {html.escape(scope['timeframe'])}, {scope['years'][0]}–{scope['years'][1]}, {html.escape(scope['source'])}. Отбор выполнялся только на TRAIN/VALIDATION с BH-FDR и реалистичными издержками.</p>
<h2>Практический вывод</h2><p>Эту спецификацию не следует торговать: статистического основания ожидать положительный результат после издержек не найдено. Закрытый TEST не использован, потому что ни один кандидат не заслужил финальной проверки.</p><p><a href="latest.json">Машиночитаемый JSON</a></p></main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")


def run() -> dict:
    REPORTS.mkdir(exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    lock = REPORTS / "private" / f"{EXPERIMENT}.test-opened.json"
    if lock.exists():
        raise RuntimeError(f"TEST for {EXPERIMENT} was already opened; create a new experiment ID")
    bars_by_symbol, funding_by_symbol, manifests = {}, {}, {}
    for symbol in SYMBOLS:
        bars, funding, manifest = download_symbol(symbol, YEARS[0], YEARS[1], DATA)
        if not bars:
            raise RuntimeError(f"No real data downloaded for {symbol}")
        bars_by_symbol[symbol], funding_by_symbol[symbol], manifests[symbol] = bars, funding, manifest
        save_normalized(symbol, bars, funding, DATA)
    write_json(ROOT / "data-manifest.json", {"experiment": EXPERIMENT, "symbols": manifests})

    btc = bars_by_symbol["BTCUSDT"]
    symbol_results = {}
    eligible = []
    for symbol in SYMBOLS:
        bars, funding = bars_by_symbol[symbol], funding_by_symbol[symbol]
        features = make_features(bars, funding, btc if symbol != "BTCUSDT" else bars)
        result = search(bars, features, funding, CostModel())
        symbol_results[symbol] = result
        if result["selected"]:
            eligible.append((symbol, result["selected"]))

    # The one frozen candidate is selected without looking at TEST.
    eligible.sort(key=lambda item: item[1]["validation"]["expectancy_ci95"][0], reverse=True)
    selected = eligible[0] if eligible else None
    frozen = {
        "experiment_id": EXPERIMENT,
        "selected_symbol": selected[0] if selected else None,
        "candidate": selected[1]["candidate"] if selected else None,
        "selection_rule": "BH-FDR significant; >=30 validation trades; positive TRAIN expectancy and validation CI lower bound",
        "costs": asdict(CostModel()),
        "feature_catalog": FEATURE_CATALOG,
        "status": "NO_CANDIDATE" if not selected else "FROZEN",
    }
    if selected:
        frozen["config_hash"] = config_hash(Candidate(**selected[1]["candidate"]))
    write_json(REPORTS / "frozen-specification.json", frozen)

    if not selected:
        report = {
            "experiment_id": EXPERIMENT,
            "completed": True,
            "test_opened": False,
            "verdict": "REJECTED",
            "reason": "No candidate survived TRAIN/VALIDATION selection and multiple-testing controls; TEST remains sealed.",
            "scope": {"source": "Binance USD-M Futures", "symbols": list(SYMBOLS), "timeframe": "1h", "years": list(YEARS)},
            "selection": {symbol: {"candidates_tested": value["candidates_tested"], "eligible": value["eligible"]} for symbol, value in symbol_results.items()},
            "frozen_specification": frozen,
            "data_quality": manifests,
        }
    else:
        symbol, chosen = selected
        bars, funding = bars_by_symbol[symbol], funding_by_symbol[symbol]
        features = make_features(bars, funding, btc if symbol != "BTCUSDT" else bars)
        splits = chronological_splits(len(bars))
        candidate = Candidate(**chosen["candidate"])
        calibration = Calibration(**chosen["calibration"])
        test_indices = list(splits["test"])
        test_trades, test_metrics = evaluate_candidate(
            candidate, bars, features, test_indices, CostModel(), dict(funding), calibration
        )
        validation_robustness = robustness(
            candidate, bars, features, list(splits["validation"]), funding, calibration
        )
        passed = test_metrics["trades"] >= 30 and (test_metrics["expectancy_ci95"][0] or -1) > 0
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock_payload = {"experiment_id": EXPERIMENT, "opened_at": datetime.now(timezone.utc).isoformat(), "git_sha": git_sha(),
                        "config_hash": frozen["config_hash"], "test_range": [splits["test"].start, splits["test"].stop]}
        write_json(lock, lock_payload)
        report = {
            "experiment_id": EXPERIMENT,
            "completed": True,
            "test_opened": True,
            "verdict": "EDGE CONFIRMED" if passed else "REJECTED",
            "reason": "Frozen candidate passed strict TEST criterion." if passed else "Frozen candidate did not retain a positive 95% expectancy interval on TEST.",
            "scope": {"source": "Binance USD-M Futures", "symbols": list(SYMBOLS), "selected_symbol": symbol, "timeframe": "1h", "years": list(YEARS)},
            "selection": {"train": chosen["train"], "validation": chosen["validation"], "candidates_tested": sum(x["candidates_tested"] for x in symbol_results.values())},
            "test": test_metrics,
            "robustness": validation_robustness,
            "frozen_specification": frozen,
            "run_manifest": lock_payload,
            "data_quality": manifests,
        }
    write_json(PUBLIC / "latest.json", report)
    write_html(PUBLIC / "latest.html", report)
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({"verdict": result["verdict"], "reason": result["reason"]}, indent=2))
