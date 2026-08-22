from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from research.altcoin_multitf_compact import (
    BAR_MS,
    BoundaryError,
    END_MS,
    START_MS,
    aggregate_bucket,
    assert_development_path,
    safe_zip_rows,
    select_roster,
    validate_funding,
    validate_kline,
)


class CompactMultitfTests(unittest.TestCase):
    def test_roster_is_top_40_deterministic_and_excludes_btc_eth(self) -> None:
        symbols = [
            {"symbol": symbol, "contractType": "PERPETUAL", "quoteAsset": "USDT", "marginAsset": "USDT", "status": "TRADING"}
            for symbol in ["BTCUSDT", "ETHUSDT", *(f"A{i:02d}USDT" for i in range(45))]
        ]
        tickers = [{"symbol": row["symbol"], "quoteVolume": str(100 if row["symbol"] in {"BTCUSDT", "ETHUSDT"} else 10)} for row in symbols]
        selected, snapshot = select_roster(json.dumps({"symbols": symbols}).encode(), json.dumps(tickers).encode())
        self.assertEqual(len(selected), 40)
        self.assertEqual(selected[:2], ["A00USDT", "A01USDT"])
        self.assertNotIn("BTCUSDT", selected)
        self.assertNotIn("ETHUSDT", selected)
        self.assertEqual(snapshot["symbol_count"], 40)

    def test_holdout_paths_fail_before_read(self) -> None:
        with self.assertRaises(BoundaryError):
            assert_development_path(Path("data/altcoin-multitf-004/sealed-holdout/x.zip"))
        with self.assertRaises(BoundaryError):
            assert_development_path(Path("data/altcoin-multitf-004/holdout/x.zip"))

    def test_zip_traversal_and_multiple_members_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bad = Path(temporary) / "bad.zip"
            with zipfile.ZipFile(bad, "w") as archive:
                archive.writestr("../escape.csv", "1,2")
            with self.assertRaises(RuntimeError):
                list(safe_zip_rows(bad))
            multiple = Path(temporary) / "multiple.zip"
            with zipfile.ZipFile(multiple, "w") as archive:
                archive.writestr("one.csv", "1")
                archive.writestr("two.csv", "2")
            with self.assertRaises(RuntimeError):
                list(safe_zip_rows(multiple))

    def test_kline_schema_ohlc_and_boundaries(self) -> None:
        valid = [str(START_MS), "10", "12", "9", "11", "2", str(START_MS + BAR_MS - 1), "21", "3", "1", "10"]
        row, issue = validate_kline(valid)
        self.assertIsNone(issue); self.assertEqual(int(row[0]), START_MS)  # type: ignore[index]
        invalid = valid.copy(); invalid[3] = "11.5"
        self.assertEqual(validate_kline(invalid)[1], "ohlc")
        boundary = valid.copy(); boundary[0] = str(END_MS)
        self.assertEqual(validate_kline(boundary)[1], "boundary")

    def test_funding_schema_and_boundaries(self) -> None:
        self.assertIsNone(validate_funding([str(START_MS), "ignored", "0.0001", "100"])[1])
        self.assertEqual(validate_funding([str(END_MS), "ignored", "0.0001", "100"])[1], "boundary")
        self.assertEqual(validate_funding([str(START_MS), "ignored", "nan", "100"])[1], "numeric")

    def test_aggregation_is_utc_closed_and_causal(self) -> None:
        rows = []
        for index in range(3):
            timestamp = START_MS + index * BAR_MS
            rows.append([str(timestamp), str(10 + index), str(12 + index), str(9 + index), str(11 + index), "2", str(timestamp + BAR_MS - 1), "20", "3", "1", "10"])
        result = aggregate_bucket(rows, START_MS, 3)
        self.assertEqual(result[0], str(START_MS))
        self.assertEqual(result[6], str(START_MS + 3 * BAR_MS - 1))
        self.assertEqual(result[4], "13")
        self.assertEqual(float(result[7]), 60)

    def test_header_and_round_trip_csv_fixture(self) -> None:
        buffer = io.StringIO(); csv.writer(buffer).writerow([START_MS, 1, 2])
        self.assertIn(str(START_MS), buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
