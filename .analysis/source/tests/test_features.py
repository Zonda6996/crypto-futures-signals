import unittest

from research.core import Bar
from research.data import validate_bars
from research.features import make_features


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.bars = [Bar(i * 3_600_000, 100 + i, 102 + i, 99 + i, 101 + i, 100 + i, 50 + i / 2) for i in range(60)]

    def test_feature_prefix_invariance(self):
        prefix = make_features(self.bars[:55], [(0, 0.001)])
        extended = make_features(self.bars, [(0, 0.001), (58 * 3_600_000, 9.0)])
        self.assertEqual(prefix[54], extended[54])

    def test_funding_is_backward_asof(self):
        rows = make_features(self.bars, [(50 * 3_600_000 + 1, 0.002)])
        self.assertIsNone(rows[50]["funding"])
        self.assertEqual(rows[51]["funding"], 0.002)

    def test_quality_finds_gap_and_invalid_ohlc(self):
        broken = [self.bars[0], Bar(2 * 3_600_000, 100, 99, 101, 100, 1)]
        quality = validate_bars(broken)
        self.assertEqual(quality["gaps"], 1)
        self.assertEqual(quality["invalid_ohlc"], 1)


if __name__ == "__main__":
    unittest.main()
