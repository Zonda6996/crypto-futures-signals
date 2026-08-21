import csv
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.phase5_falsification import (
    TEST_START_TS,
    best_continuous_cluster,
    calendar_blocks,
    deterministic_keep,
    rolling_windows,
    verdict,
)

DAY_MS = 86_400_000


def ts(year, month, day):
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


def row(timestamp, value):
    return {"signal_ts": timestamp, "result_r": value}


class Phase5FalsificationTests(unittest.TestCase):
    def test_calendar_blocks_are_chronological(self):
        rows = [row(ts(2023, 1, 1), 1), row(ts(2023, 3, 1), 2), row(ts(2023, 4, 1), -1)]
        blocks = calendar_blocks(rows, 3)
        self.assertEqual([item["period"] for item in blocks], ["2023-01", "2023-04"])
        self.assertEqual(blocks[0]["total_r"], 3)

    def test_rolling_windows_never_cross_test_boundary(self):
        rows = [row(ts(2023, 1, 1), 1), row(ts(2024, 12, 1), 2)]
        windows = rolling_windows(rows, 12)
        self.assertTrue(windows)
        self.assertTrue(all(int(datetime.fromisoformat(item["end"]).timestamp() * 1000) <= TEST_START_TS
                            for item in windows))

    def test_continuous_cluster_uses_signal_time(self):
        rows = [row(ts(2023, 1, 1), 2), row(ts(2023, 1, 20), 3), row(ts(2023, 3, 1), 10)]
        cluster = best_continuous_cluster(rows, 30)
        self.assertEqual(cluster["cluster_total_r"], 10)
        self.assertEqual(cluster["remaining_total_r"], 5)

    def test_missed_trade_sampling_is_deterministic(self):
        rows = [row(i * DAY_MS, 1) for i in range(100)]
        self.assertEqual(deterministic_keep(rows, 20, 2020), deterministic_keep(rows, 20, 2020))
        self.assertNotEqual(deterministic_keep(rows, 20, 2020), deterministic_keep(rows, 20, 2021))

    def test_verdict_requires_every_frozen_criterion(self):
        criteria = {"a": True, "b": True}
        self.assertTrue(verdict(criteria)["pass"])
        criteria["b"] = False
        result = verdict(criteria)
        self.assertFalse(result["pass"])
        self.assertEqual(result["failed"], ["b"])

    def test_committed_artifacts_are_complete_and_pre_test(self):
        output = Path(__file__).resolve().parents[1] / "reports" / "phase5"
        summary_path = output / "summary.json"
        if not summary_path.exists():
            self.skipTest("Phase 5 artifacts are generated after unit helper validation")
        result = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertFalse(result["test_opened"])
        self.assertTrue(result["separate_from_phases_2_to_4"])
        self.assertLess(result["sample"]["last_included_ts"], TEST_START_TS)
        expected = {"trades.csv": result["integrity"]["trade_rows"],
                    "calendar-blocks.csv": result["integrity"]["calendar_rows"],
                    "rolling-windows.csv": result["integrity"]["rolling_rows"],
                    "execution-scenarios.csv": result["integrity"]["scenario_rows"]}
        for filename, count in expected.items():
            with (output / filename).open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), count)
        with (output / "trades.csv").open(newline="", encoding="utf-8") as handle:
            for trade in csv.DictReader(handle):
                self.assertLess(int(trade["signal_ts"]), TEST_START_TS)
        self.assertEqual(result["verdict"]["pass"], all(result["verdict"]["criteria"].values()))
        self.assertLessEqual(result["execution_scenarios"]["adverse_slippage"]["total_r"],
                             result["baseline"]["total_r"])
        self.assertLessEqual(result["execution_scenarios"]["cost_0_16pct"]["total_r"],
                             result["baseline"]["total_r"])


if __name__ == "__main__":
    unittest.main()
