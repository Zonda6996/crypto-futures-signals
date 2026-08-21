from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research.altcoin_multitf_phase1a import (
    DEVELOPMENT_DIR,
    DEVELOPMENT_START_MS,
    HOLDOUT_END_MS,
    HOLDOUT_START_MS,
    LifecycleGateError,
    LifecycleRecord,
    RawFileRecord,
    SealedPayloadAccessError,
    atomic_store_raw,
    classify_partition,
    lifecycle_gate_issues,
    require_lifecycle_gate,
    research_read,
    validate_manifest,
)


class LifecycleGateTests(unittest.TestCase):
    def record(self, **changes):
        values = dict(
            symbol="OLDUSDT", pair="OLDUSDT", base_asset="OLD", quote_asset="USDT",
            margin_asset="USDT", contract_type="PERPETUAL", onboard_ms=1_600_000_000_000,
            delivery_ms=1_700_000_000_000, status="SETTLED",
            source_url="https://www.binance.com/en/support/announcement/example",
            source_sha256="a" * 64, acquired_at="2026-08-22T00:00:00Z",
            historical_terminal_evidence="official delisting announcement",
        )
        values.update(changes)
        return LifecycleRecord(**values)

    def test_incomplete_discovery_source_fails_closed(self):
        issues = lifecycle_gate_issues([self.record()], source_set_complete=False)
        self.assertIn("official source set does not prove exhaustive historical contract discovery", issues)
        with self.assertRaises(LifecycleGateError):
            require_lifecycle_gate([self.record()], source_set_complete=False)

    def test_current_only_roster_fails_terminal_evidence_gate(self):
        current = self.record(symbol="LIVEUSDT", status="TRADING", delivery_ms=None)
        issues = lifecycle_gate_issues([current], source_set_complete=True)
        self.assertIn("registry has no delisted/expired/failed contract evidence", issues)

    def test_missing_dates_are_not_invented(self):
        issues = lifecycle_gate_issues([self.record(onboard_ms=None)], source_set_complete=True)
        self.assertIn("missing authoritative onboard time: OLDUSDT", issues)


class SealingTests(unittest.TestCase):
    def test_boundaries_are_half_open_and_crossing_rejected(self):
        self.assertEqual(classify_partition(DEVELOPMENT_START_MS, HOLDOUT_START_MS), DEVELOPMENT_DIR)
        with self.assertRaises(ValueError):
            classify_partition(HOLDOUT_START_MS - 1, HOLDOUT_START_MS + 1)
        with self.assertRaises(ValueError):
            classify_partition(HOLDOUT_END_MS, HOLDOUT_END_MS + 1)

    def test_atomic_resume_is_idempotent_and_conflict_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = dict(source="https://data.binance.vision/example.zip", symbol="OLDUSDT",
                        datatype="klines", timeframe="5m", start_ms=DEVELOPMENT_START_MS,
                        end_exclusive_ms=DEVELOPMENT_START_MS + 300_000,
                        acquired_at="2026-08-22T00:00:00Z")
            first = atomic_store_raw(root, Path("OLDUSDT/2020-01.zip"), b"same", **args)
            second = atomic_store_raw(root, Path("OLDUSDT/2020-01.zip"), b"same", **args)
            self.assertEqual(first.sha256, second.sha256)
            with self.assertRaises(FileExistsError):
                atomic_store_raw(root, Path("OLDUSDT/2020-01.zip"), b"different", **args)

    def test_research_reader_denies_sealed_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = atomic_store_raw(
                root, Path("OLDUSDT/2026-01.zip"), b"opaque holdout bytes",
                source="https://data.binance.vision/example.zip", symbol="OLDUSDT",
                datatype="klines", timeframe="5m", start_ms=HOLDOUT_START_MS,
                end_exclusive_ms=HOLDOUT_START_MS + 300_000,
                acquired_at="2026-08-22T00:00:00Z",
            )
            with self.assertRaises(SealedPayloadAccessError):
                research_read(root / record.path, raw_root=root)

    def test_manifest_rejects_duplicate_and_partition_mismatch(self):
        row = RawFileRecord(
            path="altcoin-multitf-003/development/OLDUSDT/file.zip", size=1, sha256="a" * 64,
            source="https://data.binance.vision/file.zip", symbol="OLDUSDT", datatype="klines",
            timeframe="5m", start_ms=DEVELOPMENT_START_MS,
            end_exclusive_ms=DEVELOPMENT_START_MS + 300_000,
            acquisition_timestamp="2026-08-22T00:00:00Z", partition=DEVELOPMENT_DIR,
        )
        issues = validate_manifest([row, row])
        self.assertTrue(any(issue.startswith("duplicate path") for issue in issues))
        self.assertTrue(any(issue.startswith("duplicate logical file") for issue in issues))


if __name__ == "__main__":
    unittest.main()
