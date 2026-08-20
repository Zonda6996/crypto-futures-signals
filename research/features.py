from __future__ import annotations

from math import sqrt
from statistics import mean, pstdev
from typing import Sequence

from .core import Bar, backward_asof

FEATURE_CATALOG = {
    "ret_4": "Short-horizon continuation/reversal from four fully closed hourly bars.",
    "ret_24": "Daily momentum captures persistent information diffusion.",
    "reversal_1": "One-bar reversal tests temporary liquidity pressure.",
    "rv_24": "Realized volatility identifies risk and forced-flow regimes.",
    "atr_24": "Range-scaled volatility supports comparable exits across instruments.",
    "breakout_48": "Distance from prior 48-hour range tests slow stop/attention cascades.",
    "vwap_distance_24": "Distance from trailing VWAP tests anchoring and inventory mean reversion.",
    "abnormal_volume_24": "Relative volume tests whether moves carry unusual participation.",
    "taker_imbalance_24": "Aggressive flow imbalance tests persistent urgency.",
    "funding": "Last actually published funding rate tests crowded positioning; backward as-of joined.",
    "btc_regime": "BTC lagged daily trend conditions broad crypto risk appetite.",
    "relative_strength_24": "Alt return minus BTC return separates idiosyncratic strength.",
}


def safe_return(a: float, b: float) -> float:
    return b / a - 1 if a else 0.0


def make_features(
    bars: Sequence[Bar],
    funding: Sequence[tuple[int, float]],
    btc_bars: Sequence[Bar] | None = None,
) -> list[dict[str, float | int | str | None]]:
    btc_by_ts = {b.ts: b for b in btc_bars or bars}
    funding_values = backward_asof([b.ts for b in bars], funding, lag_ms=1)
    rows = []
    for i, bar in enumerate(bars):
        row: dict[str, float | int | str | None] = {"ts": bar.ts, "close": bar.close}
        if i < 49:
            row["ready"] = 0
            rows.append(row)
            continue
        returns = [safe_return(bars[j - 1].close, bars[j].close) for j in range(i - 23, i + 1)]
        ranges = [bars[j].high - bars[j].low for j in range(i - 23, i + 1)]
        volumes = [bars[j].volume for j in range(i - 23, i + 1)]
        value = sum(bars[j].close * bars[j].volume for j in range(i - 23, i + 1))
        volume = sum(volumes)
        prior = bars[i - 48:i]
        high, low = max(b.high for b in prior), min(b.low for b in prior)
        span = high - low
        btc_now, btc_prev = btc_by_ts.get(bar.ts), btc_by_ts.get(bars[i - 24].ts)
        btc_ret = safe_return(btc_prev.close, btc_now.close) if btc_now and btc_prev else 0.0
        ret24 = safe_return(bars[i - 24].close, bar.close)
        row.update({
            "ready": 1,
            "ret_4": safe_return(bars[i - 4].close, bar.close),
            "ret_24": ret24,
            "reversal_1": -safe_return(bars[i - 1].close, bar.close),
            "rv_24": pstdev(returns) * sqrt(24),
            "atr_24": mean(ranges),
            "breakout_48": (bar.close - (high + low) / 2) / span if span else 0.0,
            "vwap_distance_24": bar.close / (value / volume) - 1 if volume else 0.0,
            "abnormal_volume_24": bar.volume / mean(volumes) - 1 if mean(volumes) else 0.0,
            "taker_imbalance_24": sum(2 * bars[j].taker_buy_volume - bars[j].volume for j in range(i - 23, i + 1)) / volume if volume else 0.0,
            "funding": funding_values[i],
            "btc_regime": "bull" if btc_ret > 0.01 else "bear" if btc_ret < -0.01 else "range",
            "btc_return_24": btc_ret,
            "relative_strength_24": ret24 - btc_ret,
        })
        rows.append(row)
    return rows
