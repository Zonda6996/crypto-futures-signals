import unittest

from research.phase2_walk_forward_repeat import concentration, summarize_r, walk_forward_folds


class Phase2WalkForwardTests(unittest.TestCase):
    def test_folds_never_cross_available_boundary(self):
        folds = walk_forward_folds(range(0, 35_059), 14_000, 5_250, "anchored")
        self.assertEqual(folds[0]["calibration"], range(0, 14_000))
        self.assertEqual(folds[-1]["oos"].stop, 35_000)
        self.assertEqual(len(folds), 4)
        self.assertTrue(all(fold["calibration"].stop == fold["oos"].start for fold in folds))
        self.assertTrue(all(len(fold["oos"]) == 5_250 for fold in folds))

    def test_rolling_calibration_uses_fixed_trailing_window(self):
        folds = walk_forward_folds(range(0, 35_059), 14_000, 5_250, "rolling")
        self.assertTrue(all(len(fold["calibration"]) == 14_000 for fold in folds))
        self.assertGreater(folds[-1]["calibration"].start, 0)

    def test_summary_and_concentration(self):
        values = [1.0, -0.5, 0.25]
        self.assertAlmostEqual(summarize_r(values)["total_r"], 0.75)
        self.assertAlmostEqual(concentration(values)["best_5_r"], 0.75)


if __name__ == "__main__":
    unittest.main()
