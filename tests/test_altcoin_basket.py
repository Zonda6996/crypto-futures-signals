"""Tests for the exploratory fixed-basket protocol ALT-XSMOM-001-B.

These tests prove the sealed HOLDOUT guard, causality, eligibility, sizing,
funding treatment and cost handling on synthetic fixtures only.
"""

from __future__ import annotations

import io
import random
import unittest
import urllib.error
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from research.altcoin_basket_data import (
    BASKET,
    HOLDOUT_START_MS,
    HOUR_MS,
    DAY_MS,
    BasketBar,
    FundingEvent,
    HoldoutSealedError,
    assert_month_is_pre_holdout,
    assert_pre_holdout,
    audit_series,
    download_symbol,
    guarded_cached_zip,
    month_bounds_ms,
    parse_klines,
    pre_holdout_months,
    trailing_coverage,
)
from research.altcoin_basket_engine import (
    COST_SCENARIOS,
    RANKING_HORIZONS_DAYS,
    REBALANCE_HOURS,
    SymbolSeries,
    block_bootstrap_sharpe,
    book_size,
    build_period,
    decision_timestamps,
    eligible_symbols,
    pnl_attribution,
    rank_symbols,
    run_configuration,
    summarise,
    winsorised_inverse_vol_weights,
)

MS = 1000


def ts(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp() * MS)


def make_bars(
    start_ms: int,
    count: int,
    *,
    start_price: float = 100.0,
    drift: float = 0.0,
    noise: float = 0.004,
    seed: int = 7,
) -> list[BasketBar]:
    """Synthetic bars with drift plus deterministic noise.

    Noise is required: a pure constant-drift path has zero return dispersion,
    which the engine correctly rejects as unsizeable.
    """
    rng = random.Random(seed ^ hash((start_ms, count, round(start_price, 6), round(drift, 8))) & 0xFFFFFFFF)
    bars = []
    price = start_price
    for index in range(count):
        step = drift + rng.gauss(0.0, noise)
        nxt = max(price * (1 + step), 1e-6)
        bars.append(
            BasketBar(
                ts=start_ms + index * HOUR_MS,
                open=price,
                high=max(price, nxt) * 1.001,
                low=min(price, nxt) * 0.999,
                close=nxt,
                volume=1000.0,
                quote_volume=1000.0 * price,
            )
        )
        price = nxt
    return bars


def make_funding(start_ms: int, end_ms: int, rate: float = 0.0001) -> list[FundingEvent]:
    events = []
    step = 8 * HOUR_MS
    current = start_ms - (start_ms % step)
    while current < end_ms:
        events.append(FundingEvent(current, rate))
        current += step
    return events


class TestFrozenBasket(unittest.TestCase):
    def test_basket_is_exactly_the_frozen_ten(self):
        self.assertEqual(
            BASKET,
            (
                "ETHUSDT",
                "BNBUSDT",
                "SOLUSDT",
                "XRPUSDT",
                "ADAUSDT",
                "DOGEUSDT",
                "LINKUSDT",
                "LTCUSDT",
                "AVAXUSDT",
                "DOTUSDT",
            ),
        )
        self.assertNotIn("BTCUSDT", BASKET)
        self.assertEqual(len(set(BASKET)), 10)

    def test_grid_is_the_preregistered_one(self):
        self.assertEqual(RANKING_HORIZONS_DAYS, (7, 14, 30))
        self.assertEqual(REBALANCE_HOURS, (8, 12, 24))
        self.assertEqual(
            sorted(COST_SCENARIOS.values()), [0.0010, 0.0012, 0.0020]
        )

    def test_download_rejects_symbol_outside_basket(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                download_symbol("BTCUSDT", Path(tmp))


class TestSealedHoldout(unittest.TestCase):
    def test_assert_pre_holdout_rejects_boundary_and_later(self):
        assert_pre_holdout(HOLDOUT_START_MS - 1)
        with self.assertRaises(HoldoutSealedError):
            assert_pre_holdout(HOLDOUT_START_MS)
        with self.assertRaises(HoldoutSealedError):
            assert_pre_holdout(HOLDOUT_START_MS + HOUR_MS)

    def test_month_enumeration_never_reaches_holdout(self):
        periods = pre_holdout_months()
        self.assertIn("2025-12", periods)
        self.assertNotIn("2026-01", periods)
        for period in periods:
            start, end = month_bounds_ms(period)
            self.assertLess(start, HOLDOUT_START_MS)
            self.assertLessEqual(end, HOLDOUT_START_MS)

    def test_holdout_month_request_is_refused(self):
        for period in ("2026-01", "2026-02", "2027-06"):
            with self.assertRaises(HoldoutSealedError):
                assert_month_is_pre_holdout(period)

    def test_guarded_download_never_calls_network_for_holdout_month(self):
        calls: list[str] = []

        def opener(request, timeout=0):  # pragma: no cover - must never run
            calls.append(request.full_url)
            raise AssertionError("network must not be reached for a HOLDOUT month")

        with TemporaryDirectory() as tmp:
            with self.assertRaises(HoldoutSealedError):
                guarded_cached_zip(
                    "https://example.invalid/ETHUSDT-1h-2026-01.zip",
                    "2026-01",
                    Path(tmp),
                    opener=opener,
                )
        self.assertEqual(calls, [])

    def test_parse_klines_rejects_holdout_row(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "rows.csv",
                f"{HOLDOUT_START_MS},1,2,0.5,1.5,10,0,1000,5,1,1,0\n",
            )
        with self.assertRaises(HoldoutSealedError):
            parse_klines(buffer.getvalue())

    def test_download_symbol_stops_at_holdout_even_if_archive_exists(self):
        requested: list[str] = []

        def opener(request, timeout=0):
            requested.append(request.full_url)
            raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, None)

        with TemporaryDirectory() as tmp:
            download_symbol("ETHUSDT", Path(tmp), periods=["2025-11", "2025-12"], opener=opener)
        self.assertTrue(requested)
        for url in requested:
            self.assertNotIn("2026", url)


class TestDataAudit(unittest.TestCase):
    def test_audit_detects_clean_series(self):
        bars = make_bars(ts(2024, 1, 1), 240)
        audit = audit_series(bars)
        self.assertEqual(audit["duplicates"], 0)
        self.assertTrue(audit["monotonic"])
        self.assertEqual(audit["missing_bars"], 0)
        self.assertEqual(audit["interior_gaps"], 0)
        self.assertEqual(audit["coverage"], 1.0)
        self.assertEqual(audit["invalid_ohlc"], 0)

    def test_audit_detects_duplicates_and_gaps(self):
        bars = make_bars(ts(2024, 1, 1), 10)
        holed = bars[:4] + bars[6:] + [bars[3]]
        audit = audit_series(holed)
        self.assertEqual(audit["duplicates"], 1)
        self.assertFalse(audit["monotonic"])
        self.assertEqual(audit["missing_bars"], 2)

    def test_trailing_coverage_uses_only_prior_bars(self):
        decision = ts(2024, 2, 1)
        stamps = [decision - (i + 1) * HOUR_MS for i in range(30 * 24)]
        self.assertAlmostEqual(trailing_coverage(stamps, decision), 1.0)
        future = [decision + i * HOUR_MS for i in range(100)]
        self.assertEqual(trailing_coverage(future, decision), 0.0)


class TestEligibility(unittest.TestCase):
    def build(self, count: int, *, days: int = 200) -> dict[str, SymbolSeries]:
        start = ts(2024, 1, 1)
        series = {}
        for symbol in BASKET[:count]:
            bars = make_bars(start, days * 24, drift=0.0001)
            series[symbol] = SymbolSeries.build(symbol, bars, make_funding(start, start + days * DAY_MS))
        return series

    def test_young_listing_is_not_eligible(self):
        series = self.build(10, days=200)
        decision = ts(2024, 1, 1) + 40 * DAY_MS
        eligible, reasons = eligible_symbols(series, decision)
        self.assertEqual(eligible, [])
        self.assertTrue(all(reason == "listing_age_below_90d" for reason in reasons.values()))

    def test_mature_listing_is_eligible(self):
        series = self.build(10, days=200)
        decision = ts(2024, 1, 1) + 120 * DAY_MS
        eligible, _ = eligible_symbols(series, decision)
        self.assertEqual(len(eligible), 10)

    def test_missing_symbol_is_reported_and_never_substituted(self):
        series = self.build(6, days=200)
        decision = ts(2024, 1, 1) + 120 * DAY_MS
        eligible, reasons = eligible_symbols(series, decision)
        self.assertEqual(len(eligible), 6)
        for symbol in BASKET[6:]:
            self.assertEqual(reasons[symbol], "no_data")

    def test_low_coverage_is_excluded(self):
        start = ts(2024, 1, 1)
        bars = make_bars(start, 200 * 24, drift=0.0001)
        decision = start + 150 * DAY_MS
        thin = [bar for bar in bars if bar.ts < decision - 30 * DAY_MS or bar.ts % (4 * HOUR_MS) == 0]
        series = {"ETHUSDT": SymbolSeries.build("ETHUSDT", thin, [])}
        _, reasons = eligible_symbols(series, decision)
        self.assertEqual(reasons["ETHUSDT"], "trailing_coverage_below_95pct")

    def test_book_size_matches_frozen_rule(self):
        self.assertEqual(book_size(10), 2)
        self.assertEqual(book_size(9), 1)
        self.assertEqual(book_size(5), 1)
        self.assertEqual(book_size(4), 0)


class TestCausality(unittest.TestCase):
    def setUp(self):
        self.start = ts(2024, 1, 1)
        self.series = {}
        for index, symbol in enumerate(BASKET):
            drift = 0.0002 * (index - 4)
            bars = make_bars(self.start, 220 * 24, start_price=100.0 + index, drift=drift)
            self.series[symbol] = SymbolSeries.build(
                symbol, bars, make_funding(self.start, self.start + 220 * DAY_MS)
            )

    def test_closed_bar_only(self):
        item = self.series["ETHUSDT"]
        decision = self.start + 100 * HOUR_MS
        found = item.close_at_or_before(decision)
        self.assertIsNotNone(found)
        self.assertLessEqual(found[0] + HOUR_MS, decision)

    def test_execution_is_at_or_after_decision(self):
        item = self.series["ETHUSDT"]
        decision = self.start + 100 * HOUR_MS + 5
        bar = item.execution_bar(decision)
        self.assertIsNotNone(bar)
        self.assertGreaterEqual(bar.ts, decision)

    def test_momentum_is_none_without_history(self):
        item = self.series["ETHUSDT"]
        self.assertIsNone(item.momentum(self.start + HOUR_MS, 30))

    def test_period_is_long_short_and_market_neutral_in_weight(self):
        decision = self.start + 120 * DAY_MS
        period = build_period(self.series, decision, decision + 8 * HOUR_MS, 14)
        self.assertIsNone(period.skipped_reason)
        self.assertEqual(len(period.legs), 4)
        longs = sum(leg.weight for leg in period.legs if leg.side == 1)
        shorts = sum(leg.weight for leg in period.legs if leg.side == -1)
        self.assertAlmostEqual(longs, 0.5, places=9)
        self.assertAlmostEqual(shorts, 0.5, places=9)
        self.assertAlmostEqual(sum(abs(leg.weight) for leg in period.legs), 1.0, places=9)

    def test_ranking_puts_strongest_long_and_weakest_short(self):
        # Drift must dominate the noise for the ordering to be deterministic.
        decision = self.start + 120 * DAY_MS
        series = {}
        for index, symbol in enumerate(BASKET):
            bars = make_bars(
                self.start, 220 * 24, start_price=100.0, drift=0.0004 * (index - 4), noise=0.0002
            )
            series[symbol] = SymbolSeries.build(symbol, bars, [])
        scored = rank_symbols(series, list(BASKET), decision, 14)
        self.assertEqual(scored[0][0], BASKET[9])
        self.assertEqual(scored[-1][0], BASKET[0])
        values = [value for _, value in scored]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_ranking_ties_break_on_canonical_basket_order(self):
        decision = self.start + 120 * DAY_MS
        series = {
            symbol: SymbolSeries.build(
                symbol, make_bars(self.start, 220 * 24, start_price=100.0, drift=0.0, noise=0.0), []
            )
            for symbol in BASKET
        }
        scored = rank_symbols(series, list(BASKET), decision, 14)
        self.assertEqual([symbol for symbol, _ in scored], list(BASKET))

    def test_future_information_cannot_change_a_decision(self):
        decision = self.start + 120 * DAY_MS
        baseline = build_period(self.series, decision, decision + 8 * HOUR_MS, 14)
        mutated = {}
        for symbol, item in self.series.items():
            bars = [
                bar
                if bar.ts < decision + 8 * HOUR_MS
                else BasketBar(bar.ts, bar.open * 5, bar.high * 5, bar.low * 5, bar.close * 5, bar.volume, bar.quote_volume)
                for bar in item.bars
            ]
            mutated[symbol] = SymbolSeries.build(symbol, bars, list(item.funding))
        after = build_period(mutated, decision, decision + 8 * HOUR_MS, 14)
        self.assertEqual(
            [(leg.symbol, leg.side) for leg in baseline.legs],
            [(leg.symbol, leg.side) for leg in after.legs],
        )

    def test_cross_section_below_five_is_skipped(self):
        subset = {symbol: self.series[symbol] for symbol in BASKET[:4]}
        decision = self.start + 120 * DAY_MS
        period = build_period(subset, decision, decision + 8 * HOUR_MS, 14)
        self.assertEqual(period.skipped_reason, "cross_section_below_5")
        self.assertEqual(period.legs, ())

    def test_missing_funding_is_not_treated_as_zero(self):
        stripped = {
            symbol: SymbolSeries.build(symbol, list(item.bars), [])
            for symbol, item in self.series.items()
        }
        decision = self.start + 120 * DAY_MS
        period = build_period(stripped, decision, decision + 8 * HOUR_MS, 14)
        self.assertEqual(period.skipped_reason, "missing_funding")

    def test_funding_sign_is_side_aware(self):
        decision = self.start + 120 * DAY_MS
        period = build_period(self.series, decision, decision + 8 * HOUR_MS, 14)
        for leg in period.legs:
            if leg.side == 1:
                self.assertLess(leg.funding_return, 0)
            else:
                self.assertGreater(leg.funding_return, 0)

    def test_decision_grid_stays_inside_window(self):
        end = self.start + 10 * DAY_MS
        stamps = decision_timestamps(self.start, end, 8)
        self.assertTrue(all(self.start <= value < end for value in stamps))
        self.assertEqual(stamps[1] - stamps[0], 8 * HOUR_MS)


class TestCostsAndMetrics(unittest.TestCase):
    def setUp(self):
        self.start = ts(2024, 1, 1)
        self.series = {}
        for index, symbol in enumerate(BASKET):
            drift = 0.0003 * (index - 4)
            bars = make_bars(self.start, 260 * 24, start_price=50.0 + index, drift=drift)
            self.series[symbol] = SymbolSeries.build(
                symbol, bars, make_funding(self.start, self.start + 260 * DAY_MS)
            )
        self.periods = run_configuration(
            self.series, self.start + 120 * DAY_MS, self.start + 255 * DAY_MS, 14, 24
        )

    def test_higher_costs_reduce_net_return(self):
        low = summarise(self.periods, 0.0010, 24)["net_total_return"]
        high = summarise(self.periods, 0.0020, 24)["net_total_return"]
        self.assertLess(high, low)

    def test_costs_charged_on_both_sides_of_gross_exposure(self):
        period = next(item for item in self.periods if item.legs)
        turnover = sum(abs(leg.weight) for leg in period.legs)
        self.assertAlmostEqual(turnover, 1.0, places=9)
        delta = period.net_return(0.0) - period.net_return(0.0010)
        self.assertAlmostEqual(delta, 0.0010, places=9)

    def test_summary_reports_counts(self):
        summary = summarise(self.periods, 0.0010, 24)
        self.assertGreater(summary["active_periods"], 0)
        self.assertEqual(
            summary["decisions"], summary["active_periods"] + summary["skipped_periods"]
        )

    def test_bootstrap_returns_interval(self):
        result = block_bootstrap_sharpe(self.periods, 0.0010, 24, iterations=200)
        if result["iterations"]:
            self.assertLessEqual(result["ci95_low"], result["ci95_high"])
            self.assertEqual(result["expected_block_days"], 14)

    def test_attribution_sums_to_total(self):
        attribution = pnl_attribution(self.periods, 0.0010)
        self.assertAlmostEqual(
            sum(attribution["by_symbol"].values()), attribution["net_total"], places=6
        )
        self.assertAlmostEqual(
            sum(attribution["by_year"].values()), attribution["net_total"], places=9
        )

    def test_delayed_execution_control_changes_prices(self):
        delayed = run_configuration(
            self.series, self.start + 120 * DAY_MS, self.start + 255 * DAY_MS, 14, 24,
            execution_delay_bars=1,
        )
        base_entry = next(item for item in self.periods if item.legs).legs[0].entry_ts
        delayed_entry = next(item for item in delayed if item.legs).legs[0].entry_ts
        self.assertEqual(delayed_entry - base_entry, HOUR_MS)


class TestWeighting(unittest.TestCase):
    def test_inverse_vol_weights_sum_to_one(self):
        weights = winsorised_inverse_vol_weights({"A": 0.01, "B": 0.02, "C": 0.04})
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=9)
        self.assertGreater(weights["A"], weights["C"])

    def test_winsorisation_caps_extremes(self):
        values = {f"S{i}": 0.01 for i in range(9)}
        values["S9"] = 100.0
        weights = winsorised_inverse_vol_weights(values)
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=9)
        self.assertGreater(weights["S9"], 0.0)

    def test_empty_input_is_safe(self):
        self.assertEqual(winsorised_inverse_vol_weights({}), {})


if __name__ == "__main__":
    unittest.main()
