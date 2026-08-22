import unittest

from research.phase3_robustness import COSTS, WINDOWS, neighbor_candidates


class Phase3RobustnessTests(unittest.TestCase):
    def test_costs_match_predeclared_round_trip_rates(self):
        expected = {
            "round_trip_0.05pct": 0.0005,
            "round_trip_0.10pct": 0.0010,
            "round_trip_0.12pct": 0.0012,
            "round_trip_0.16pct": 0.0016,
        }
        for label, value in expected.items():
            self.assertAlmostEqual(COSTS[label].round_trip_return, value)

    def test_neighbors_change_one_axis_only(self):
        variants = neighbor_candidates()
        frozen = variants.pop("frozen")
        self.assertEqual(len(variants), 11)
        for candidate in variants.values():
            differences = sum(a != b for a, b in zip(candidate.__dict__.values(), frozen.__dict__.values()))
            self.assertEqual(differences, 1)

    def test_windows_are_predeclared_and_positive(self):
        self.assertEqual(set(WINDOWS), {"short", "phase2_base", "long"})
        self.assertTrue(all(initial > 0 and oos > 0 for initial, oos in WINDOWS.values()))


if __name__ == "__main__":
    unittest.main()
