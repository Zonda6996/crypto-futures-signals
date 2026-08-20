from __future__ import annotations

import unittest
from datetime import datetime, timezone

from research.core import Trade, assert_selection_indices, chronological_splits
from research.phase2_walk_forward import aggregate_rows, calendar_windows, stitch_trades
from research.search import calibrate_candidate
from research.phase1_audit import CANDIDATE


def month_timestamps(year: int, month: int, count: int) -> list[int]:
    result = []
    current_year, current_month = year, month
    for _ in range(count):
        result.append(int(datetime(current_year, current_month, 1, tzinfo=timezone.utc).timestamp() * 1000))
        current_month += 1
        if current_month == 13:
            current_year += 1
            current_month = 1
    return result


def trade(signal: int, entry: int, exit_: int, net: float = 0.01) -> Trade:
    return Trade(1, signal, entry, exit_, 100, 101, 1, net, 0, 0, net, "time")


class Phase2WindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.timestamps = month_timestamps(2021, 1, 48)
        self.allowed_stop = 39

    def test_windows_are_sequential_and_calibration_precedes_oos(self) -> None:
        windows = calendar_windows(self.timestamps, self.allowed_stop, 12, 3, True)
        self.assertGreater(len(windows), 1)
        for previous, current in zip(windows, windows[1:]):
            self.assertEqual(previous.oos_stop, current.oos_start)
        for window in windows:
            self.assertLess(window.calibration_start, window.calibration_stop)
            self.assertEqual(window.calibration_stop, window.oos_start)
            self.assertLessEqual(window.oos_stop, self.allowed_stop)

    def test_anchored_and_rolling_history_boundaries(self) -> None:
        anchored = calendar_windows(self.timestamps, self.allowed_stop, 12, 3, True)
        rolling = calendar_windows(self.timestamps, self.allowed_stop, 12, 3, False)
        self.assertTrue(all(window.calibration_start == 0 for window in anchored))
        self.assertEqual([window.calibration_start for window in rolling[:3]], [0, 3, 6])
        self.assertTrue(all(window.calibration_stop == window.oos_start for window in rolling))

    def test_windows_cannot_cross_sealed_test(self) -> None:
        splits = chronological_splits(48)
        windows = calendar_windows(self.timestamps, splits["validation"].stop, 12, 3, False)
        for window in windows:
            assert_selection_indices(range(window.calibration_start, window.oos_stop), splits)
            self.assertLessEqual(window.oos_stop, splits["validation"].stop)
        with self.assertRaises(RuntimeError):
            assert_selection_indices([splits["test"].start], splits)

    def test_calibration_uses_only_supplied_past_indices(self) -> None:
        features = [
            {"ready": True, "vwap_distance_24": float(i), "rv_24": float(i + 1)}
            for i in range(20)
        ]
        first = calibrate_candidate(CANDIDATE, features, list(range(8)))
        changed_future = [dict(row) for row in features]
        for i in range(8, 20):
            changed_future[i]["vwap_distance_24"] = 1_000_000.0
            changed_future[i]["rv_24"] = 1_000_000.0
        second = calibrate_candidate(CANDIDATE, changed_future, list(range(8)))
        self.assertEqual(first, second)
        expanded = calibrate_candidate(CANDIDATE, features, list(range(12)))
        self.assertNotEqual(first, expanded)


class Phase2AggregationTests(unittest.TestCase):
    def test_stitch_removes_duplicates_and_overlaps(self) -> None:
        first = trade(1, 2, 5)
        overlap = trade(4, 5, 8)
        later = trade(9, 10, 12)
        self.assertEqual(stitch_trades([[first, overlap], [first, later]]), [first, later])

    def test_r_aggregation_drawdown_and_concentration(self) -> None:
        rows = [
            {"result_r": value, "net_return": value / 100}
            for value in (2.0, -1.0, -2.0, 4.0)
        ]
        result = aggregate_rows(rows)
        self.assertEqual(result["trades"], 4)
        self.assertAlmostEqual(result["expectancy_r"], 0.75)
        self.assertAlmostEqual(result["total_r"], 3.0)
        self.assertAlmostEqual(result["max_drawdown_r"], -3.0)
        self.assertAlmostEqual(result["profit_factor_r"], 2.0)
        self.assertAlmostEqual(result["concentration"]["best_1_share"], 4 / 3)
        expected_compounded = 1.02 * 0.99 * 0.98 * 1.04 - 1
        self.assertAlmostEqual(result["compounded_return"], expected_compounded)


if __name__ == "__main__":
    unittest.main()
