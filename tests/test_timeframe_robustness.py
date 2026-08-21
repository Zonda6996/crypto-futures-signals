import unittest

from research.core import Bar
from research.features import make_features
from research.timeframe_robustness import SEALED_TEST_START_TS, scaled_candidate, seal_before_test


class TimeframeRobustnessTests(unittest.TestCase):
    def test_hour_windows_are_scaled_without_changing_frozen_rules(self):
        m30 = scaled_candidate(2)
        m15 = scaled_candidate(4)
        self.assertEqual(m30.horizon, 48)
        self.assertEqual(m15.horizon, 96)
        self.assertEqual(m30.feature, "vwap_distance_24")
        self.assertEqual(m15.stop_atr, 1.5)
        self.assertEqual(m15.take_atr, 2.0)

    def test_test_bars_are_removed_before_research(self):
        bars = [
            Bar(SEALED_TEST_START_TS - 900_000, 1, 2, 0.5, 1.5, 10),
            Bar(SEALED_TEST_START_TS, 1, 2, 0.5, 1.5, 10),
        ]
        sealed = seal_before_test(bars)
        self.assertEqual(len(sealed), 1)
        self.assertLess(sealed[-1].ts, SEALED_TEST_START_TS)

    def test_m15_features_use_24_clock_hours_and_are_prefix_invariant(self):
        step = 900_000
        bars = [Bar(i * step, 100 + i, 102 + i, 99 + i, 101 + i, 100 + i, 50) for i in range(210)]
        prefix = make_features(bars[:200], [], bars[:200], bars_per_hour=4)
        extended = make_features(bars, [], bars, bars_per_hour=4)
        self.assertEqual(prefix[199], extended[199])
        self.assertEqual(prefix[192]["ready"], 0)
        self.assertEqual(prefix[193]["ready"], 1)
        expected = bars[199].close / bars[103].close - 1
        self.assertAlmostEqual(prefix[199]["ret_24"], expected)


if __name__ == "__main__":
    unittest.main()
