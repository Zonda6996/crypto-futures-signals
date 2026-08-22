import ast
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.altcoin_phase_a_audit import (
    DAY_MS,
    HOLDOUT_START_MS,
    ContractRecord,
    VolumeObservation,
    artifact_manifest,
    guarded_fetch,
    read_guarded_json,
    registry_issues,
    select_point_in_time_universe,
    write_guarded_json,
)


def ts(year, month, day, hour=0):
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def contract(symbol, base, onboard, delist=None, provenance="historical_exchange_snapshot"):
    return ContractRecord(symbol, base, "USDT", "PERPETUAL", onboard, delist, "TRADING", provenance, ts(2025, 1, 1))


def hourly(symbol, start, count, volume):
    return [VolumeObservation(symbol, start + index * 3_600_000, volume) for index in range(count)]


class PhaseACutoffTests(unittest.TestCase):
    def test_holdout_request_rejected_before_network(self):
        calls = []

        def opener(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("network must not be reached")

        with self.assertRaises(RuntimeError):
            guarded_fetch("https://example.invalid", start_ms=HOLDOUT_START_MS,
                          end_exclusive_ms=HOLDOUT_START_MS + 1, opener=opener)
        self.assertEqual(calls, [])

    def test_holdout_cache_write_and_read_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            with self.assertRaises(RuntimeError):
                write_guarded_json(path, {"open_time_ms": HOLDOUT_START_MS},
                                   max_timestamp_ms=HOLDOUT_START_MS)
            path.write_text(json.dumps({"open_time_ms": HOLDOUT_START_MS}), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                read_guarded_json(path, timestamp_fields=("open_time_ms",))


class PointInTimeUniverseTests(unittest.TestCase):
    def setUp(self):
        self.decision = ts(2025, 7, 1)
        self.start = self.decision - 30 * DAY_MS

    def test_ranking_uses_trailing_data_only(self):
        records = [
            contract("AAAUSDT", "AAA", ts(2024, 1, 1)),
            contract("BBBUSDT", "BBB", ts(2024, 1, 1)),
        ]
        rows = hourly("AAAUSDT", self.start, 720, 10) + hourly("BBBUSDT", self.start, 720, 9)
        rows.append(VolumeObservation("BBBUSDT", self.decision + 1, 1_000_000))
        members, _ = select_point_in_time_universe(records, rows, decision_ms=self.decision, top_n=1)
        self.assertEqual([member.symbol for member in members], ["AAAUSDT"])

    def test_listings_delistings_missing_bars_ties_and_exclusions(self):
        records = [
            contract("AAAUSDT", "AAA", ts(2024, 1, 1)),
            contract("BBBUSDT", "BBB", ts(2024, 1, 1)),
            contract("NEWUSDT", "NEW", self.decision - 89 * DAY_MS),
            contract("OLDUSDT", "OLD", ts(2024, 1, 1), self.decision),
            contract("GAPUSDT", "GAP", ts(2024, 1, 1)),
            contract("USDCUSDT", "USDC", ts(2024, 1, 1)),
            contract("WBTCUSDT", "WBTC", ts(2024, 1, 1)),
            contract("ABCUPUSDT", "ABCUP", ts(2024, 1, 1)),
        ]
        rows = hourly("AAAUSDT", self.start, 720, 10) + hourly("BBBUSDT", self.start, 720, 10)
        rows += hourly("NEWUSDT", self.start, 720, 99) + hourly("OLDUSDT", self.start, 720, 99)
        rows += hourly("GAPUSDT", self.start, 100, 99)
        members, exclusions = select_point_in_time_universe(records, rows, decision_ms=self.decision)
        self.assertEqual([member.symbol for member in members], ["AAAUSDT", "BBBUSDT"])
        self.assertEqual(exclusions["NEWUSDT"], "listing_age_below_90d")
        self.assertEqual(exclusions["OLDUSDT"], "already_delisted")
        self.assertEqual(exclusions["GAPUSDT"], "trailing_coverage_below_95pct")
        self.assertEqual(exclusions["USDCUSDT"], "stablecoin_base")
        self.assertEqual(exclusions["WBTCUSDT"], "wrapped_or_pegged_duplicate")
        self.assertEqual(exclusions["ABCUPUSDT"], "leveraged_token")

    def test_current_roster_cannot_replace_historical_registry(self):
        records = [contract("AAAUSDT", "AAA", ts(2024, 1, 1), provenance="current_exchange_info")]
        issues = registry_issues(records)
        self.assertIn("current exchange roster cannot establish a historical registry", issues)
        self.assertIn("registry contains no recoverable delisted contracts", issues)

    def test_repeated_fixture_has_same_membership_and_checksums(self):
        records = [contract("AAAUSDT", "AAA", ts(2024, 1, 1))]
        rows = hourly("AAAUSDT", self.start, 720, 10)
        first, _ = select_point_in_time_universe(records, rows, decision_ms=self.decision)
        second, _ = select_point_in_time_universe(records, list(reversed(rows)), decision_ms=self.decision)
        self.assertEqual(first, second)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            write_guarded_json(path, [member.__dict__ for member in first], max_timestamp_ms=self.decision)
            self.assertEqual(artifact_manifest([path]), artifact_manifest([path]))

    def test_entry_point_does_not_import_old_test_runner(self):
        module_path = Path(__file__).resolve().parents[1] / "research" / "altcoin_phase_a_audit.py"
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        self.assertFalse(any("test_opening" in name for name in imported))
        self.assertFalse(any(name.startswith("research.search") for name in imported))


if __name__ == "__main__":
    unittest.main()
