from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research.altcoin_multitf_phase1a import (
    DEVELOPMENT_DIR, DEVELOPMENT_START_MS, HOLDOUT_END_MS, HOLDOUT_START_MS,
    RosterGateError, RawFileRecord, SealedPayloadAccessError, atomic_store_raw,
    classify_partition, freeze_current_roster, research_read, validate_manifest,
)


class CurrentRosterGateTests(unittest.TestCase):
    def payload(self) -> bytes:
        return json.dumps({"symbols": [
            {"symbol": "ETHUSDT", "pair": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT",
             "marginAsset": "USDT", "contractType": "PERPETUAL", "status": "TRADING", "onboardDate": 1},
            {"symbol": "OLDUSDT", "baseAsset": "OLD", "quoteAsset": "USDT", "marginAsset": "USDT",
             "contractType": "PERPETUAL", "status": "SETTLING"},
            {"symbol": "BTCUSDC", "baseAsset": "BTC", "quoteAsset": "USDC", "marginAsset": "USDC",
             "contractType": "PERPETUAL", "status": "TRADING"},
        ]}).encode()

    def test_a1_accepts_current_roster_without_delisted_evidence(self):
        rows, snapshot = freeze_current_roster(self.payload(), source_url="https://fapi.binance.com/fapi/v1/exchangeInfo",
                                                acquired_at="2026-08-22T00:00:00Z")
        self.assertEqual([row.symbol for row in rows], ["ETHUSDT"])
        self.assertEqual(snapshot["symbol_count"], 1)
        self.assertEqual(len(snapshot["raw_sha256"]), 64)

    def test_empty_or_unofficial_roster_fails_closed(self):
        with self.assertRaises(RosterGateError):
            freeze_current_roster(b"", source_url="https://fapi.binance.com/fapi/v1/exchangeInfo", acquired_at="x")
        with self.assertRaises(RosterGateError):
            freeze_current_roster(self.payload(), source_url="https://example.com/exchangeInfo", acquired_at="x")

    def test_duplicate_current_symbols_fail(self):
        item = json.loads(self.payload())["symbols"][0]
        with self.assertRaises(RosterGateError):
            freeze_current_roster(json.dumps({"symbols": [item, item]}).encode(),
                                  source_url="https://fapi.binance.com/fapi/v1/exchangeInfo", acquired_at="x")


class SealingTests(unittest.TestCase):
    def test_boundaries_are_half_open_and_crossing_rejected(self):
        self.assertEqual(classify_partition(DEVELOPMENT_START_MS, HOLDOUT_START_MS), DEVELOPMENT_DIR)
        with self.assertRaises(ValueError): classify_partition(HOLDOUT_START_MS - 1, HOLDOUT_START_MS + 1)
        with self.assertRaises(ValueError): classify_partition(HOLDOUT_END_MS, HOLDOUT_END_MS + 1)

    def test_atomic_resume_is_idempotent_and_conflict_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = dict(source="https://data.binance.vision/example.zip", symbol="ETHUSDT", datatype="klines",
                        timeframe="5m", start_ms=DEVELOPMENT_START_MS, end_exclusive_ms=DEVELOPMENT_START_MS + 300_000,
                        acquired_at="2026-08-22T00:00:00Z")
            first = atomic_store_raw(root, Path("ETHUSDT/2020-01.zip"), b"same", **args)
            second = atomic_store_raw(root, Path("ETHUSDT/2020-01.zip"), b"same", **args)
            self.assertEqual(first.sha256, second.sha256)
            with self.assertRaises(FileExistsError):
                atomic_store_raw(root, Path("ETHUSDT/2020-01.zip"), b"different", **args)

    def test_research_reader_denies_sealed_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = atomic_store_raw(root, Path("ETHUSDT/2026-01.zip"), b"opaque holdout bytes",
                source="https://data.binance.vision/example.zip", symbol="ETHUSDT", datatype="klines", timeframe="5m",
                start_ms=HOLDOUT_START_MS, end_exclusive_ms=HOLDOUT_START_MS + 300_000,
                acquired_at="2026-08-22T00:00:00Z")
            with self.assertRaises(SealedPayloadAccessError): research_read(root / record.path, raw_root=root)

    def test_manifest_rejects_duplicates_and_detects_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = atomic_store_raw(root, Path("ETHUSDT/file.zip"), b"x", source="https://data.binance.vision/file.zip",
                symbol="ETHUSDT", datatype="klines", timeframe="5m", start_ms=DEVELOPMENT_START_MS,
                end_exclusive_ms=DEVELOPMENT_START_MS + 300_000, acquired_at="2026-08-22T00:00:00Z")
            issues = validate_manifest([row, row])
            self.assertTrue(any(issue.startswith("duplicate path") for issue in issues))
            (root / row.path).write_bytes(b"changed")
            self.assertTrue(any("filesystem checksum mismatch" in issue for issue in validate_manifest([row], root=root)))


if __name__ == "__main__": unittest.main()
