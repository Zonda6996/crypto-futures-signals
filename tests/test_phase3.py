from __future__ import annotations

import unittest

from research.core import Bar
from research.phase3_parameter_map import (
    BASELINE,
    add_vwap_features,
    is_immediate_neighbor,
    parameter_grid,
    summarize_cluster,
)


class Phase3FeatureTests(unittest.TestCase):
    def test_vwap_uses_current_and_past_bars_only(self) -> None:
        bars = [Bar(i, 1, 2, 0.5, float(i + 1), float(i + 1), 0) for i in range(80)]
        features = [{"ready": True} for _ in bars]
        original = add_vwap_features(bars, features)
        changed = list(bars)
        changed[79] = Bar(79, 1, 2, 0.5, 1_000_000, 1_000_000, 0)
        altered = add_vwap_features(changed, features)
        self.assertEqual(original[78]["vwap_distance_72"], altered[78]["vwap_distance_72"])
        self.assertNotEqual(original[79]["vwap_distance_72"], altered[79]["vwap_distance_72"])

    def test_vwap_requires_complete_window(self) -> None:
        bars = [Bar(i, 1, 2, 0.5, 1, 1, 0) for i in range(72)]
        rows = add_vwap_features(bars, [{"ready": True} for _ in bars])
        self.assertIsNone(rows[70]["vwap_distance_72"])
        self.assertEqual(rows[71]["vwap_distance_72"], 0.0)


class Phase3GridTests(unittest.TestCase):
    def test_grid_is_pre_registered_cartesian_product(self) -> None:
        grid = parameter_grid()
        self.assertEqual(len(grid), 256)
        self.assertEqual(len(set(grid)), 256)
        self.assertIn(BASELINE, grid)

    def test_only_adjacent_single_axis_points_are_neighbors(self) -> None:
        self.assertTrue(is_immediate_neighbor((12, 1.5, 2.0, 24)))
        self.assertTrue(is_immediate_neighbor((24, 1.8, 2.0, 24)))
        self.assertFalse(is_immediate_neighbor(BASELINE))
        self.assertFalse(is_immediate_neighbor((72, 1.5, 2.0, 24)))
        self.assertFalse(is_immediate_neighbor((12, 1.8, 2.0, 24)))

    def test_cluster_rule_uses_center_and_neighbors_not_best_point(self) -> None:
        points = [BASELINE, (12, 1.5, 2.0, 24), (48, 1.5, 2.0, 24)]
        rows = []
        for index, point in enumerate(points):
            rows.append({
                "cost_scenario": "round_trip_0_10pct",
                "vwap_hours": point[0], "stop_atr": point[1], "take_atr": point[2], "hold_hours": point[3],
                "is_baseline": point == BASELINE, "is_immediate_neighbor": point != BASELINE,
                "expectancy_r": (0.1, 0.2, -0.1)[index], "total_r": (1.0, 2.0, -1.0)[index],
            })
        result = summarize_cluster(rows)
        self.assertTrue(result["positive_cluster"])
        self.assertAlmostEqual(result["baseline_neighborhood"]["positive_expectancy_share"], 2 / 3)


if __name__ == "__main__":
    unittest.main()
