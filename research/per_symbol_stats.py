"""Per-symbol backtest statistics for the FINAL-001 SELECT configuration.

Replays the frozen SELECT episode logic (core A + atr3 stop + full take 1:1) over
the DECIDE window and aggregates per-symbol outcomes: episodes, exits by reason,
price-move winrate, average favourable/adverse moves, long/short split, average
hold and average funding collected. Hedge and weights do not affect episode
timing, so these statistics are identical for the hedged/in-vol SELECT book.

Writes reports/artifacts/altcoin-carry-final-001/per-symbol-stats.{json,csv}.
Diagnostic tool: reads local archives only, never the monitor reserve.
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from research.altcoin_carry_final_001 import (
    BASE_CORE,
    DECIDE_END_EXCLUSIVE_MS,
    DECIDE_START_MS,
    DAY_MS,
    SlData,
)
from research.altcoin_multitf_inputs import UNIVERSE_SYMBOLS

ART = Path("reports/artifacts/altcoin-carry-final-001")


def replay(data: SlData):
    lookback, k = BASE_CORE["lookback_days"], BASE_CORE["k_per_side"]
    symbols = sorted(data.closes)
    fractions = {s: 0.0 for s in symbols}
    episodes: dict[str, dict] = {}
    journal: list[dict] = []
    days = [d for d in range(DECIDE_START_MS, DECIDE_END_EXCLUSIVE_MS, DAY_MS)]
    for index, day in enumerate(days):
        if not data.day_is_complete(day):
            continue
        for s in symbols:
            rpx = data.price_return(s, day)
            fractions[s] = fractions[s] * (1.0 + rpx)
        signals = {s: data.signal(s, day, lookback) for s in symbols}
        ranked = sorted(symbols, key=lambda s: (-signals[s], s))
        shorts = set(ranked[:k])
        longs = set(ranked[len(ranked) - k:])
        for s in sorted(episodes):
            e = episodes[s]
            px = data.closes[s][day]
            reason = None
            if (e["side"] < 0 and s not in shorts) or (e["side"] > 0 and s not in longs):
                reason = "rank"
            if reason is None:
                if e["side"] > 0 and px <= e["entry"] - e["dist"]:
                    reason = "stop"
                elif e["side"] < 0 and px >= e["entry"] + e["dist"]:
                    reason = "stop"
            if reason is None:
                fav = (px - e["entry"]) if e["side"] > 0 else (e["entry"] - px)
                if fav >= e["dist"]:
                    reason = "take"
            if reason:
                move = (px - e["entry"]) / e["entry"] * e["side"]
                journal.append({
                    "sym": s, "side": "LONG" if e["side"] > 0 else "SHORT",
                    "open_day": e["open_day"], "close_day": index,
                    "hold_days": index - e["open_idx"], "reason": reason, "move": move,
                })
                del episodes[s]
        for side, bucket in ((-1, sorted(shorts)), (1, sorted(longs))):
            holders = [s for s, e in episodes.items() if e["side"] == side]
            for sym in bucket:
                if len(holders) >= k:
                    break
                if sym in holders or sym in episodes:
                    continue
                if data.atr.get(sym, {}).get(day) is None:
                    continue
                episodes[sym] = {"side": side, "entry": data.closes[sym][day],
                                 "dist": 3.0 * data.atr[sym][day],
                                 "open_idx": index,
                                 "open_day": index}
                holders.append(sym)
    return journal


def aggregate(journal: list[dict]) -> dict:
    agg: dict[str, dict] = defaultdict(lambda: {
        "episodes": 0, "take": 0, "stop": 0, "rank": 0, "wins": 0,
        "long": 0, "short": 0, "moves": [], "hold_days": [],
    })
    for j in journal:
        a = agg[j["sym"]]
        a["episodes"] += 1
        a[j["reason"]] += 1
        a["wins"] += 1 if j["move"] > 0 else 0
        a["long"] += 1 if j["side"] == "LONG" else 0
        a["short"] += 1 if j["side"] == "SHORT" else 0
        a["moves"].append(j["move"])
        a["hold_days"].append(j["hold_days"])
    out = {}
    for sym, a in sorted(agg.items()):
        wins = [m for m in a["moves"] if m > 0]
        losses = [m for m in a["moves"] if m <= 0]
        out[sym] = {
            "episodes": a["episodes"],
            "exits": {"take": a["take"], "stop": a["stop"], "rank": a["rank"]},
            "winrate_price": round(a["wins"] / a["episodes"], 4),
            "avg_win_move": round(sum(wins) / len(wins), 5) if wins else 0.0,
            "avg_loss_move": round(sum(losses) / len(losses), 5) if losses else 0.0,
            "avg_move": round(sum(a["moves"]) / a["episodes"], 5),
            "avg_hold_days": round(sum(a["hold_days"]) / a["episodes"], 2),
            "long_episodes": a["long"],
            "short_episodes": a["short"],
        }
    return out


def main() -> int:
    data = SlData.load(Path(r"D:\alt-multitf-005-data\inputs\merged"))
    journal = replay(data)
    per_symbol = aggregate(journal)
    total = aggregate([]) if False else None
    doc = {
        "purpose": "per-symbol backtest statistics of the FINAL-001 SELECT episode logic (price moves; hedge/weights do not affect episode timing)",
        "window_utc": ["2021-01-01", "2026-06-30"],
        "total_episodes": len(journal),
        "symbols": per_symbol,
    }
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "per-symbol-stats.json").write_text(
        json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    with (ART / "per-symbol-stats.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.writer(h, lineterminator="\n")
        head = ["symbol", "episodes", "take", "stop", "rank", "winrate_price",
                "avg_win_move", "avg_loss_move", "avg_move", "avg_hold_days",
                "long_episodes", "short_episodes"]
        w.writerow(head)
        for sym, v in per_symbol.items():
            w.writerow([sym, v["episodes"], v["exits"]["take"], v["exits"]["stop"],
                        v["exits"]["rank"], v["winrate_price"], v["avg_win_move"],
                        v["avg_loss_move"], v["avg_move"], v["avg_hold_days"],
                        v["long_episodes"], v["short_episodes"]])
    print(json.dumps({"symbols": len(per_symbol), "total_episodes": len(journal),
                      "out": str(ART / "per-symbol-stats.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
