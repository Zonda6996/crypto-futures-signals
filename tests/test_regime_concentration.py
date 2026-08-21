import unittest

from research.core import Bar
from research.regime_concentration import (
    COST,
    SEALED_TEST_START_TS,
    TIMEFRAMES,
    _past_medians,
    causal_btc_regimes,
    summarize_values,
)


class RegimeConcentrationTests(unittest.TestCase):
    def test_threshold_uses_strictly_past_values(self):
        values = [1.0, 100.0, 3.0, 4.0]
        thresholds = _past_medians(values, minimum=2)
        self.assertEqual(thresholds, [None, None, 50.5, 3.0])

    def test_regimes_are_prefix_invariant(self):
        step = 3_600_000
        count = 90 * 24 + 80
        bars = [
            Bar(i * step, 100 + i / 10, 101 + i / 10, 99 + i / 10, 100 + i / 10, 10)
            for i in range(count + 10)
        ]
        prefix = causal_btc_regimes(bars[:count], 1)
        extended = causal_btc_regimes(bars, 1)
        self.assertEqual(prefix[-1], extended[count - 1])

    def test_current_value_does_not_change_its_threshold(self):
        step = 3_600_000
        count = 90 * 24 + 80
        bars = [Bar(i * step, 100, 101, 99, 100 + i / 100, 10) for i in range(count)]
        changed = list(bars)
        last = changed[-1]
        changed[-1] = Bar(last.ts, last.open, 1000, last.low, 999, last.volume)
        original = causal_btc_regimes(bars, 1)[-1]
        mutated = causal_btc_regimes(changed, 1)[-1]
        self.assertEqual(original["trend_threshold_past_median"], mutated["trend_threshold_past_median"])
        self.assertEqual(original["volatility_threshold_past_median"], mutated["volatility_threshold_past_median"])

    def test_test_boundary_and_frozen_cost_are_explicit(self):
        self.assertEqual(SEALED_TEST_START_TS, 1_735_689_600_000)
        self.assertEqual(set(TIMEFRAMES), {"1h", "30m", "15m"})
        self.assertAlmostEqual(COST.round_trip_return, 0.001)

    def test_summary_artifact_has_all_concentration_fields(self):
        summary = summarize_values([2.0, 1.0, -1.0, -0.5, 0.25, 0.1])
        self.assertEqual(summary["trades"], 6)
        for count in (1, 3, 5):
            self.assertIn(f"top_{count}_profit_share", summary)
            self.assertIn(f"without_top_{count}_r", summary)
            self.assertIn(f"without_top_{count}_expectancy_r", summary)


if __name__ == "__main__":
    unittest.main()
