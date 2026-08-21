import unittest

from research.core import Bar, CostModel
from research.features import make_features
from research.search import Calibration, Candidate, benjamini_hochberg, candidate_grid, evaluate_candidate


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.bars = [Bar(i * 3_600_000, 100 + i * 0.1, 101 + i * 0.1, 99 + i * 0.1,
                         100.2 + i * 0.1, 100, 55) for i in range(200)]
        self.features = make_features(self.bars, [])

    def test_grid_has_separate_long_and_short(self):
        sides = {candidate.side for candidate in candidate_grid()}
        horizons = {candidate.horizon for candidate in candidate_grid()}
        self.assertEqual(sides, {-1, 1})
        self.assertEqual(horizons, {4, 12, 24})

    def test_evaluation_uses_only_given_indices(self):
        candidate = Candidate("ret_4", 1, 0.75, 4, "all", "all", 1.5, 2.0)
        trades, _ = evaluate_candidate(candidate, self.bars, self.features, list(range(50, 100)), CostModel(), {})
        self.assertTrue(all(50 <= t.signal_ts // 3_600_000 < 100 for t in trades))

    def test_validation_uses_frozen_train_calibration(self):
        candidate = Candidate("ret_4", 1, 0.75, 4, "all", "high", 1.5, 2.0)
        frozen = Calibration(threshold=999.0, rv_median=999.0)
        trades, result = evaluate_candidate(
            candidate, self.bars, self.features, list(range(100, 180)), CostModel(), {}, frozen
        )
        self.assertEqual(trades, [])
        self.assertEqual(result["threshold"], 999.0)

    def test_bh_rejects_only_small_p_values(self):
        records = [{"validation": {"p_value": p}} for p in (0.0001, 0.01, 0.8)]
        benjamini_hochberg(records)
        self.assertTrue(records[0]["fdr_significant"])
        self.assertTrue(records[1]["fdr_significant"])
        self.assertFalse(records[2]["fdr_significant"])


if __name__ == "__main__":
    unittest.main()
