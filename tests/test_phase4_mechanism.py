import unittest

from research.phase4_mechanism import bootstrap_difference, non_overlapping


class Phase4MechanismTests(unittest.TestCase):
    def test_non_overlapping_events_respect_spacing(self):
        selected = non_overlapping([1, 2, 25, 26, 27, 52], spacing=24)
        self.assertEqual(selected, [1, 26, 52])
        self.assertTrue(all(right - left > 24 for left, right in zip(selected, selected[1:])))

    def test_bootstrap_difference_is_deterministic(self):
        first = bootstrap_difference([0.1, 0.2, 0.3], [-0.1, 0.0, 0.1], samples=100)
        second = bootstrap_difference([0.1, 0.2, 0.3], [-0.1, 0.0, 0.1], samples=100)
        self.assertEqual(first, second)
        self.assertAlmostEqual(first["difference"], 0.2)


if __name__ == "__main__":
    unittest.main()
