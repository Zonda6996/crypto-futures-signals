from __future__ import annotations

import random
import unittest
from datetime import datetime, timezone

from research.altcoin_basket_data import BASKET, DAY_MS, HOLDOUT_START_MS, HOUR_MS, BasketBar, FundingEvent, HoldoutSealedError
from research.altcoin_basket_engine import SymbolSeries
from research.altcoin_long_only_engine import (
    ANNUAL_DAYS, BASE_WEIGHT, BOOTSTRAP_BLOCK_DAYS, MOMENTUM_DAYS, REBALANCE_HOUR_UTC,
    REBALANCE_WEEKDAY, TOP_K, VOL_WINDOW_DAYS, causal_rank, constraint_violations,
    run_train, target_holdings, volatility_multiplier, weekly_decisions,
)


def ts(year, month, day, hour=0):
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def fixture(days=240):
    start = ts(2024, 1, 1)
    universe = {}
    for index, symbol in enumerate(BASKET):
        rng = random.Random(index)
        bars = []; price = 50.0 + index
        for hour in range(days * 24 + 1):
            drift = (index - 4) * .00003 + rng.gauss(0, .001)
            nxt = price * (1 + drift)
            bars.append(BasketBar(start + hour * HOUR_MS, price, max(price, nxt), min(price, nxt), nxt, 1000, 1_000_000 + index * 1000))
            price = nxt
        funding = [FundingEvent(start + hour * HOUR_MS, .00001) for hour in range(0, days * 24 + 1, 8)]
        universe[symbol] = SymbolSeries.build(symbol, bars, funding)
    return start, universe


class TestFrozenMechanics(unittest.TestCase):
    def test_constants_are_frozen(self):
        self.assertEqual((MOMENTUM_DAYS, TOP_K, BASE_WEIGHT), (30, 4, .25))
        self.assertEqual((REBALANCE_WEEKDAY, REBALANCE_HOUR_UTC), (0, 0))
        self.assertEqual((VOL_WINDOW_DAYS, ANNUAL_DAYS, BOOTSTRAP_BLOCK_DAYS), (30, 365, 30))

    def test_weekly_grid_is_monday_midnight_and_guarded(self):
        stamps = weekly_decisions(ts(2024, 1, 1), ts(2024, 2, 1))
        self.assertTrue(stamps)
        for value in stamps:
            dt = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
            self.assertEqual((dt.weekday(), dt.hour), (0, 0))
        with self.assertRaises(HoldoutSealedError):
            weekly_decisions(ts(2025, 12, 1), HOLDOUT_START_MS + DAY_MS)

    def test_vol_warmup_and_scaling(self):
        self.assertEqual(volatility_multiplier([.01] * 29), 0.0)
        self.assertEqual(volatility_multiplier([0.0] * 30), 0.0)
        self.assertGreater(volatility_multiplier([-.01, .01] * 15), 0.0)
        self.assertLessEqual(volatility_multiplier([-.01, .01] * 15), 1.0)


class TestCausalityAndConstruction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start, cls.universe = fixture()
        cls.decision = cls.start + 120 * DAY_MS

    def test_future_mutation_cannot_change_rank(self):
        baseline = causal_rank(self.universe, self.decision)
        changed = {}
        for symbol, item in self.universe.items():
            bars = [bar if bar.ts < self.decision else BasketBar(bar.ts, bar.open * 9, bar.high * 9, bar.low * 9, bar.close * 9, bar.volume, bar.quote_volume) for bar in item.bars]
            changed[symbol] = SymbolSeries.build(symbol, bars, item.funding)
        self.assertEqual(baseline, causal_rank(changed, self.decision))

    def test_top_four_long_only_equal_preweights_and_caps(self):
        holdings, multiplier, status = target_holdings(self.universe, self.decision, 1.0)
        self.assertEqual(status, "active")
        self.assertEqual(len(holdings), 4)
        self.assertTrue(all(0 <= h.weight <= .25 for h in holdings))
        self.assertTrue(all(h.weight <= h.participation_cap for h in holdings))
        self.assertLessEqual(sum(h.weight for h in holdings), 1.0)
        self.assertGreater(multiplier, 0)

    def test_less_than_five_eligible_means_cash(self):
        subset = {symbol: self.universe[symbol] for symbol in BASKET[:4]}
        holdings, multiplier, status = target_holdings(subset, self.decision, 1.0)
        self.assertEqual((holdings, multiplier, status), ((), 0.0, "eligible_below_5"))

    def test_constraint_checker_detects_no_valid_violation(self):
        holdings, _, _ = target_holdings(self.universe, self.decision, 1.0)
        self.assertEqual(constraint_violations(holdings, self.decision, self.decision), ())

    def test_integration_is_deterministic_and_pre_holdout(self):
        end = self.start + 200 * DAY_MS
        first = run_train(self.universe, self.start + 100 * DAY_MS, end)
        second = run_train(self.universe, self.start + 100 * DAY_MS, end)
        self.assertEqual(first, second)
        self.assertTrue(first)
        self.assertTrue(all(r.day_ms < HOLDOUT_START_MS for r in first))
        self.assertTrue(all(not r.violations for r in first))
        self.assertTrue(all(len(r.holdings) in (0, 4) for r in first))


if __name__ == "__main__":
    unittest.main()
