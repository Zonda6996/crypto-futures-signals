"""Paper-forward runner for the ALTCOIN_CARRY_FINAL-001 SELECT configuration.

Runs the frozen SAFE arm (core A + atr3 stop + full take 1:1 + BTC beta-hedge +
inverse-vol weights) and, separately labelled, the published RISK arm
(A + atr3 + partial 1:2 + breakeven), on LIVE Binance USDT-M daily data.

Rules of engagement:
- append-only journal under reports/artifacts/altcoin-carry-final-001/forward/;
- the runner processes only fully CLOSED daily bars and never backfills trades:
  the first run starts the journal at the current date; earlier calendar days
  (including the sealed monitor reserve 2026-07..08) are consumed exclusively as
  indicator warmup and are never evaluated;
- decision logic is a pure function of (bars, funding, state) and is unit-tested;
- no parameter may be changed without a new freeze.

Usage:
  uv run python -m research.altcoin_carry_forward --run     # fetch + advance
  uv run python -m research.altcoin_carry_forward --status  # print report
"""
from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from research.altcoin_multitf_inputs import UNIVERSE_SYMBOLS
from research.altcoin_multitf_supplement import fetch_retry

ART = Path("reports/artifacts/altcoin-carry-final-001/forward")
KLINES_URL = "https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1d&limit=160"
FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=1000&startTime={start_ms}"
DAY_MS = 86_400_000
BTC = "BTCUSDT"

SAFE = "SAFE"
RISK = "RISK"
MODES = (SAFE, RISK)

ATR_PERIOD = 14
SIGMA_WINDOW = 30
BETA_WINDOW = 90
LOOKBACK_DAYS = 3
K_PER_SIDE = 3
STOP_ATR_MULT = 3.0
BLOWUP_CAP = 2.0
COST_PER_FILL = 6.0e-4
WARMUP_BARS = 120


# ---------------------------------------------------------------------------
# pure decision core (unit-tested; no IO)


def wilder_atr_series(closes: list[float], highs: list[float], lows: list[float]) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    smoothed = None
    trs: list[float] = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        if smoothed is None:
            trs.append(tr)
            if len(trs) == ATR_PERIOD:
                smoothed = sum(trs) / ATR_PERIOD
                out[i] = smoothed
            continue
        smoothed = ((ATR_PERIOD - 1) * smoothed + tr) / ATR_PERIOD
        out[i] = smoothed
    return out


def _returns_ending(closes: list[float], last_index: int, count: int) -> list[float] | None:
    if last_index - count < 0:
        return None
    return [closes[i] / closes[i - 1] - 1.0 for i in range(last_index - count + 1, last_index + 1)]


def trailing_sigma(closes: list[float], decision_index: int) -> float | None:
    """Sigma of returns ending at the close BEFORE the decision bar (causal)."""
    rs = _returns_ending(closes, decision_index - 1, SIGMA_WINDOW)
    if rs is None:
        return None
    mean = sum(rs) / len(rs)
    return (sum((v - mean) ** 2 for v in rs) / len(rs)) ** 0.5


def trailing_beta(closes: list[float], btc_closes: list[float], decision_index: int) -> float:
    rs = _returns_ending(closes, decision_index - 1, BETA_WINDOW)
    rb = _returns_ending(btc_closes, decision_index - 1, BETA_WINDOW)
    if rs is None or rb is None:
        return 1.0
    ms = sum(rs) / len(rs)
    mb = sum(rb) / len(rb)
    cov = sum((a - ms) * (b - mb) for a, b in zip(rs, rb)) / len(rs)
    var = sum((b - mb) ** 2 for b in rb) / len(rb)
    return cov / var if var > 0 else 1.0


def funding_signal(events: list[tuple[int, float]], bar_open_ms: int) -> float | None:
    """Mean funding rate over the LOOKBACK_DAYS calendar days ending at the bar."""
    window_start = bar_open_ms - (LOOKBACK_DAYS - 1) * DAY_MS
    window_end = bar_open_ms + DAY_MS  # inclusive of the bar's own day
    rates = [r for ts, r in events if window_start <= ts < window_end]
    if not rates:
        return None
    return sum(rates) / len(rates)


def decide_bar(mode: str, state: dict, market: dict, costs: float = COST_PER_FILL) -> dict:
    """Advance one mode's state over one closed decision bar.

    market: {symbol: {"close", "atr", "ret", "sigma", "beta"}, "funding_mean": {symbol: mean|None}}
    state:  {"episodes": {sym: {side, entry, dist, entry_date}}, "fractions": {sym: f},
             "hedge_frac": float, "banned": {sym}, "equity": float, "last_open_ms": int}
    Returns the new state plus an events list. Pure: inputs are not mutated.
    """
    btc_close = market[BTC]["close"]
    btc_ret = market[BTC]["ret"]
    fractions = dict(state["fractions"])
    episodes = {k: dict(v) for k, v in state["episodes"].items()}
    banned = set(state.get("banned", ()))
    equity = state["equity"]

    # mark-to-market over this bar with the PREVIOUS fractions (incl. hedge leg)
    total_prev = dict(fractions)
    if mode == SAFE:
        total_prev[BTC] = total_prev.get(BTC, 0.0) + state.get("hedge_frac", 0.0)
    bar_ret = 0.0
    for sym, f in total_prev.items():
        bar_ret += f * market[sym]["ret"]
    equity *= 1.0 + bar_ret

    turnover = 0.0
    events: list[dict] = []

    # exits on this bar's close
    for symbol in sorted(episodes):
        episode = episodes[symbol]
        px = market[symbol]["close"]
        dist_eff = 0.0 if episode.get("be") else episode["dist"]
        reason = None
        if (episode["side"] < 0 and symbol not in state["shorts"]) or (
            episode["side"] > 0 and symbol not in state["longs"]
        ):
            reason = "rank_drop"
        if reason is None:
            if episode["side"] > 0 and px <= episode["entry"] - dist_eff:
                reason = "stop"
            elif episode["side"] < 0 and px >= episode["entry"] + dist_eff:
                reason = "stop"
        if reason is None and mode == SAFE:
            favorable = (px - episode["entry"]) if episode["side"] > 0 else (episode["entry"] - px)
            if favorable >= episode["dist"]:
                reason = "take"
        if reason is None and mode == RISK and not episode.get("taken"):
            favorable = (px - episode["entry"]) if episode["side"] > 0 else (episode["entry"] - px)
            if favorable >= 2.0 * episode["dist"]:
                half = abs(fractions[symbol]) / 2.0
                turnover += half
                fractions[symbol] -= half if fractions[symbol] > 0 else -half
                episode["taken"] = True
                episode["be"] = True
                events.append({"type": "partial", "symbol": symbol, "side": episode["side"],
                               "entry": episode["entry"], "mark": px, "date": state.get("pending_date")})
        if reason:
            turnover += abs(fractions[symbol])
            fractions[symbol] = 0.0
            del episodes[symbol]
            if reason != "rank_drop":
                banned.add(symbol)
            events.append({"type": reason, "symbol": symbol, "side": episode["side"],
                           "entry": episode["entry"], "exit": px, "date": state.get("pending_date")})

    # refills
    for side, bucket in ((-1, state["shorts"]), (1, state["longs"])):
        holders = [s for s, e in episodes.items() if e["side"] == side]
        for symbol in sorted(bucket):
            if len(holders) >= K_PER_SIDE:
                break
            if symbol in holders or symbol in episodes or symbol in banned:
                continue
            atr = market[symbol]["atr"]
            if not atr or atr <= 0:
                continue
            entry = market[symbol]["close"]
            episodes[symbol] = {"side": side, "entry": entry, "dist": STOP_ATR_MULT * atr,
                                "entry_date": state.get("pending_date")}
            holders.append(symbol)
            events.append({"type": "open", "symbol": symbol,
                           "side_name": "LONG" if side > 0 else "SHORT", "entry": entry})

    # targets
    held = list(episodes)
    if mode == SAFE and held:
        invols = {}
        for symbol in held:
            sigma = market[symbol]["sigma"]
            invols[symbol] = (1.0 / sigma) if sigma and sigma > 0 else None
        known = [s for s in held if invols[s] is not None]
        denom = sum(invols[s] for s in known)
        for symbol in symbols_all():
            target = 0.0
            if symbol in episodes:
                side = episodes[symbol]["side"]
                target = side * (invols[symbol] / denom if symbol in known and denom > 0 else 1.0 / K_PER_SIDE)
            turnover += abs(target - fractions.get(symbol, 0.0))
            fractions[symbol] = target
    else:
        for symbol in symbols_all():
            target = 0.0
            if symbol in episodes:
                target = (1.0 / K_PER_SIDE) if episodes[symbol]["side"] > 0 else -(1.0 / K_PER_SIDE)
            turnover += abs(target - fractions.get(symbol, 0.0))
            fractions[symbol] = target

    # anti-blowup cap
    for symbol in symbols_all():
        cap = BLOWUP_CAP / K_PER_SIDE
        if abs(fractions.get(symbol, 0.0)) > cap:
            signed_cap = cap if fractions[symbol] > 0 else -cap
            turnover += abs(signed_cap - fractions[symbol])
            fractions[symbol] = signed_cap

    # hedge (SAFE only)
    hedge_frac = state.get("hedge_frac", 0.0)
    if mode == SAFE:
        beta_book = sum(fractions[s] * market[s]["beta"] for s in symbols_all())
        new_hedge = -beta_book
        turnover += abs(new_hedge - hedge_frac)
        hedge_frac = new_hedge
    else:
        hedge_frac = 0.0

    equity *= max(0.0, 1.0 - costs * turnover)

    return {
        "state": {
            "episodes": episodes, "fractions": fractions, "hedge_frac": hedge_frac,
            "banned": sorted(banned), "equity": equity,
            "shorts": sorted(state["shorts"]), "longs": sorted(state["longs"]),
            "last_open_ms": state["last_open_ms"],
        },
        "events": events,
        "bar_ret": bar_ret,
        "turnover": turnover,
    }


def symbols_all() -> tuple[str, ...]:
    return UNIVERSE_SYMBOLS


def empty_state(equity: float = 1.0) -> dict:
    return {
        "episodes": {}, "fractions": {s: 0.0 for s in UNIVERSE_SYMBOLS},
        "hedge_frac": 0.0, "banned": [], "equity": equity,
        "shorts": [], "longs": [], "last_open_ms": 0,
    }


# ---------------------------------------------------------------------------
# IO / live plumbing


def _bars_from_klines(payload: list) -> tuple[list[int], list[float], list[float], list[float]]:
    now_ms = int(time.time() * 1000)
    opens, closes, highs, lows = [], [], [], []
    for k in payload:
        open_ms = int(k[0])
        if open_ms + DAY_MS > now_ms:
            continue  # drop the forming bar
        opens.append(open_ms)
        closes.append(float(k[4]))
        highs.append(float(k[2]))
        lows.append(float(k[3]))
    return opens, closes, highs, lows


def fetch_market() -> dict:
    """Fetch closed daily bars + funding for the universe. Returns per-symbol
    indicator snapshot for the latest closed bar plus funding means per day."""
    closes_map: dict[str, list[float]] = {}
    atr_map: dict[str, float | None] = {}
    ret_map: dict[str, float] = {}
    sigma_map: dict[str, float | None] = {}
    beta_map: dict[str, float] = {}
    last_open: int | None = None
    funding_by_day: dict[str, dict[int, float]] = {}

    for symbol in UNIVERSE_SYMBOLS:
        payload = json.loads(fetch_retry(KLINES_URL.format(symbol=symbol)))
        opens, closes, highs, lows = _bars_from_klines(payload)
        if last_open is None:
            last_open = opens[-1]
        assert opens[-1] == last_open, f"bar misalignment for {symbol}"
        closes_map[symbol] = closes
        atr_series = wilder_atr_series(closes, highs, lows)
        atr_map[symbol] = atr_series[-1]
        ret_map[symbol] = closes[-1] / closes[-2] - 1.0
        sigma_map[symbol] = trailing_sigma(closes, len(closes) - 1)
        beta_map[symbol] = trailing_beta(closes, closes_map.get(BTC, closes), len(closes) - 1)
        fpayload = json.loads(fetch_retry(FUNDING_URL.format(
            symbol=symbol, start_ms=int(time.time() * 1000) - 45 * DAY_MS)))
        by_day: dict[int, float] = {}
        for item in fpayload:
            ts = int(item["fundingTime"])
            ts = ts - ts % DAY_MS
            by_day[ts] = by_day.get(ts, 0.0) + float(item["fundingRate"])
        funding_by_day[symbol] = by_day

    # funding means per closed day (for catch-up decisions)
    day_means: dict[int, dict[str, float | None]] = {}
    for day in sorted({d for m in funding_by_day.values() for d in m}):
        row = {}
        for symbol in UNIVERSE_SYMBOLS:
            window = [funding_by_day[symbol].get(day - o * DAY_MS) for o in (0, 1, 2)]
            vals = [v for v in window if v is not None]
            row[symbol] = sum(vals) / len(vals) if vals else None
        day_means[day] = row
    return {
        "last_open": last_open, "closes": closes_map, "atr": atr_map, "ret": ret_map,
        "sigma": sigma_map, "beta": beta_map, "funding_day_means": day_means,
    }


def rank_book(day_means: dict[str, float | None]) -> tuple[set[str], set[str]] | None:
    if any(v is None for v in day_means.values()):
        return None
    ranked = sorted(UNIVERSE_SYMBOLS, key=lambda s: (-day_means[s], s))
    return set(ranked[:K_PER_SIDE]), set(ranked[len(ranked) - K_PER_SIDE:])


def run_once() -> dict:
    ART.mkdir(parents=True, exist_ok=True)
    state_path = ART / "state.json"
    trades_path = ART / "trades.jsonl"
    states = {}
    if state_path.exists():
        states = json.loads(state_path.read_text(encoding="utf-8"))
    for mode in MODES:
        states.setdefault(mode, empty_state())
    market = fetch_market()
    last_open = market["last_open"]

    # strict no-backfill: process ONLY the latest closed bar; if the runner was
    # offline for missed days, they are logged as a gap and skipped entirely
    # (the sealed reserve 2026-07..08 is never evaluated)
    day = last_open
    processed = 0
    means = market["funding_day_means"].get(day)
    book = rank_book(means) if means is not None else None
    for mode in MODES:
        st = states[mode]
        if st["last_open_ms"] >= day:
            continue
        gap_days = None if st["last_open_ms"] == 0 else (day - st["last_open_ms"]) // DAY_MS - 1
        if book is None:
            st["last_open_ms"] = day
            continue
        shorts, longs = book
        st["shorts"], st["longs"], st["pending_date"] = sorted(shorts), sorted(longs), \
            datetime.fromtimestamp(day / 1000, tz=timezone.utc).date().isoformat()
        market_day = {s: {"close": market["closes"][s][-1], "ret": market["ret"][s],
                          "atr": market["atr"][s], "sigma": market["sigma"][s],
                          "beta": market["beta"][s]} for s in UNIVERSE_SYMBOLS}
        outcome = decide_bar(mode, st, market_day)
        states[mode] = outcome["state"]
        states[mode]["last_open_ms"] = day
        if gap_days:
            outcome["events"].insert(0, {"type": "gap", "missed_days": gap_days,
                                         "date": st["pending_date"]})
        with trades_path.open("a", encoding="utf-8") as handle:
            for event in outcome["events"]:
                handle.write(json.dumps({"mode": mode, "day": st["pending_date"], **event},
                                        sort_keys=True) + "\n")
        processed += 1
    states["_meta"] = {
        "last_run_utc": datetime.now(tz=timezone.utc).isoformat(),
        "last_closed_bar_utc": datetime.fromtimestamp(last_open / 1000, tz=timezone.utc).date().isoformat(),
        "processed_this_run": processed,
        "journal_starts": "first run date; no backfill over the sealed reserve",
    }
    write_json_atomic(state_path, states)
    return states


def write_json_atomic(path: Path, payload) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def status() -> str:
    state_path = ART / "state.json"
    if not state_path.exists():
        return "forward journal not started yet — run with --run"
    states = json.loads(state_path.read_text(encoding="utf-8"))
    lines = [f"last run: {states['_meta']['last_run_utc']}",
             f"last closed bar: {states['_meta']['last_closed_bar_utc']}"]
    for mode in MODES:
        st = states[mode]
        lines.append(f"--- {mode}: equity(mark) {st['equity']:.6f}, hedge {st.get('hedge_frac', 0):+.4f}")
        for sym, e in sorted(st["episodes"].items()):
            lines.append(f"    {e['side']:+d} {sym:10} entry {e['entry']:.4f} dist {e['dist']:.4f} since {e.get('entry_date')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", action="store_true")
    group.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    if args.run:
        states = run_once()
        print(json.dumps({m: {"equity": states[m]["equity"],
                              "episodes": len(states[m]["episodes"]),
                              "hedge": states[m].get("hedge_frac", 0.0)} for m in MODES} |
                         {"meta": states["_meta"]}, indent=1, sort_keys=True, default=str))
    else:
        print(status())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
