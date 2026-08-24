"""Paper-forward decision-core tests (pure functions, no network)."""
from __future__ import annotations

import pytest

from research.altcoin_carry_forward import (
    BTC,
    DAY_MS,
    RISK,
    SAFE,
    decide_bar,
    empty_state,
    funding_signal,
    rank_book,
    trailing_beta,
    trailing_sigma,
    wilder_atr_series,
)
from research.altcoin_multitf_inputs import UNIVERSE_SYMBOLS


def market_for(**overrides):
    market = {}
    for s in UNIVERSE_SYMBOLS:
        m = {"close": 100.0, "ret": 0.0, "atr": 1.0, "sigma": 0.01, "beta": 1.0}
        m.update(overrides.get(s, {}))
        market[s] = m
    return market


def fresh_state(**kw):
    st = empty_state()
    st.update(kw)
    return st


# ---------------------------------------------------------------------------
# indicators


def test_funding_signal_three_day_window() -> None:
    t0 = 1_700_000_000_000
    t0 -= t0 % DAY_MS
    events = [(t0, 0.0001), (t0 + DAY_MS, 0.0002), (t0 + 2 * DAY_MS, 0.0003),
              (t0 + 5 * DAY_MS, 0.999)]
    bar = t0 + 2 * DAY_MS
    assert funding_signal(events, bar) == pytest.approx(0.0002)  # mean of 3-day window
    assert funding_signal([], bar) is None


def test_trailing_sigma_excludes_decision_bar() -> None:
    closes = [100.0] * 40
    for i in range(30, 40):
        closes[i] = 100.0 * (1.01 if i % 2 else 0.99)
    sigma_at_last = trailing_sigma(closes, len(closes) - 1)
    # decision bar itself (a huge move) must not enter the window
    closes_shocked = closes[:-1] + [120.0]
    assert trailing_sigma(closes_shocked, len(closes_shocked) - 1) == pytest.approx(sigma_at_last)


def test_trailing_beta_two_for_doubled_moves() -> None:
    btc = [100.0] * 95
    sym = [100.0] * 95
    for i in range(5, 95):
        step = 0.01 if i % 2 else -0.01
        btc[i] = btc[i - 1] * (1 + step)
        sym[i] = sym[i - 1] * (1 + 2 * step)
    assert trailing_beta(sym, btc, 94) == pytest.approx(2.0, rel=1e-6)


def test_wilder_atr_constant_range() -> None:
    closes = [100.5] * 30
    highs = [101.0] * 30
    lows = [100.0] * 30
    atr = wilder_atr_series(closes, highs, lows)
    assert atr[-1] == pytest.approx(1.0)
    assert atr[0] is None


def test_rank_book_ties_alphabetical() -> None:
    means = {s: 0.0005 for s in UNIVERSE_SYMBOLS}
    shorts, longs = rank_book(means)
    assert shorts == set(sorted(UNIVERSE_SYMBOLS)[:3])
    assert longs == set(sorted(UNIVERSE_SYMBOLS)[-3:])


# ---------------------------------------------------------------------------
# decide_bar


def test_first_bar_opens_six_episodes_and_hedge() -> None:
    market = market_for()
    st = fresh_state(shorts=["ADAUSDT", "AVAXUSDT", "BNBUSDT"],
                     longs=["LINKUSDT", "SOLUSDT", "XRPUSDT"], pending_date="2026-08-24")
    out = decide_bar(SAFE, st, market)
    assert len(out["state"]["episodes"]) == 6
    # uniform betas, dollar-neutral book -> net beta zero -> hedge flat
    assert out["state"]["hedge_frac"] == pytest.approx(0.0, abs=1e-12)
    kinds = [e["type"] for e in out["events"]]
    assert kinds.count("open") == 6


def test_hedge_shorts_btc_when_long_side_beta_dominates() -> None:
    market = market_for(**{"SOLUSDT": {"beta": 4.0}})
    st = fresh_state(shorts=["ADAUSDT", "AVAXUSDT", "BNBUSDT"],
                     longs=["LINKUSDT", "SOLUSDT", "XRPUSDT"], pending_date="d")
    out = decide_bar(SAFE, st, market)
    # longs beta sum 6/3=2 avg vs shorts 1 -> beta_book = (4+1+1)/6 - 3/6 = +0.5
    assert out["state"]["hedge_frac"] == pytest.approx(-0.5)


def test_stop_fires_and_bans_symbol() -> None:
    market = market_for(**{"SOLUSDT": {"close": 96.0, "ret": -0.04}})
    st = fresh_state(
        episodes={"SOLUSDT": {"side": 1, "entry": 100.0, "dist": 3.0, "entry_date": "d"}},
        fractions={"SOLUSDT": 1 / 3}, shorts=[], longs=["SOLUSDT"], pending_date="d")
    out = decide_bar(SAFE, st, market)
    assert "SOLUSDT" not in out["state"]["episodes"]
    assert "SOLUSDT" in out["state"]["banned"]
    assert out["events"][0]["type"] == "stop"


def test_take_fires_at_one_r() -> None:
    market = market_for(**{"SOLUSDT": {"close": 103.0, "ret": 0.03}})
    st = fresh_state(
        episodes={"SOLUSDT": {"side": 1, "entry": 100.0, "dist": 3.0, "entry_date": "d"}},
        fractions={"SOLUSDT": 1 / 3}, shorts=[], longs=["SOLUSDT"], pending_date="d")
    out = decide_bar(SAFE, st, market)
    assert out["events"][0]["type"] == "take"


def test_rank_drop_exits_without_ban() -> None:
    st = fresh_state(
        episodes={"SOLUSDT": {"side": 1, "entry": 100.0, "dist": 3.0, "entry_date": "d"}},
        fractions={"SOLUSDT": 1 / 3}, shorts=["ADAUSDT"], longs=["BNBUSDT"], pending_date="d")
    out = decide_bar(SAFE, st, market_for())
    assert "SOLUSDT" not in out["state"]["episodes"]
    assert "SOLUSDT" not in out["state"]["banned"]


def test_risk_partial_halves_and_moves_breakeven() -> None:
    market = market_for(**{"SOLUSDT": {"close": 106.0, "ret": 0.06}})
    st = fresh_state(
        episodes={"SOLUSDT": {"side": 1, "entry": 100.0, "dist": 3.0, "entry_date": "d"}},
        fractions={"SOLUSDT": 1 / 3}, shorts=[], longs=["SOLUSDT"], pending_date="d")
    out = decide_bar(RISK, st, market)
    assert out["state"]["episodes"]["SOLUSDT"]["taken"] is True
    assert out["state"]["episodes"]["SOLUSDT"]["be"] is True
    assert any(e["type"] == "partial" for e in out["events"])
    # frozen semantics: the daily trim restores the target weight after the
    # partial harvest (matches the SL-001 backtest exactly)
    assert out["state"]["fractions"]["SOLUSDT"] == pytest.approx(1 / 3)
    # breakeven: any close below entry now stops the remainder
    out2 = decide_bar(RISK, out["state"], market_for(**{"SOLUSDT": {"close": 99.0, "ret": -0.01}}))
    assert any(e["type"] == "stop" for e in out2["events"])


def test_equity_marks_previous_book() -> None:
    st = fresh_state(fractions={"BTCUSDT": 0.5}, equity=1.0, shorts=[], longs=[], pending_date="d")
    market = market_for(**{"BTCUSDT": {"ret": 0.02}})
    out = decide_bar(SAFE, st, market)
    assert out["bar_ret"] == pytest.approx(0.01)  # 0.5 * 2% (hedge was 0)
