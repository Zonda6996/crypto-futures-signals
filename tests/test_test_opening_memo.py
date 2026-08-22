from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research import test_opening
from research.test_opening_integrity import FROZEN_SHA, MANIFEST_PATH, TEST_START, verify_all


class TestOpeningMemoIntegrityTests(unittest.TestCase):
    def test_manifest_and_all_committed_hashes_match(self):
        result = verify_all(require_source_cache=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["pretest_source_files"], 192)

    def test_manifest_is_strictly_pretest(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(manifest["frozen_research_commit"], FROZEN_SHA)
        self.assertEqual(manifest["test_boundary"], TEST_START)
        for source in manifest["pretest_sources"].values():
            self.assertEqual(source["years"], [2021, 2024])
            self.assertTrue(all(item["period"] < "2025-01" for item in source["files"]))

    def test_memo_contains_single_primary_verdict_and_exact_command(self):
        memo = (MANIFEST_PATH.parent / "TEST_OPENING_MEMO.md").read_text(encoding="utf-8")
        self.assertIn("Единственный primary metric", memo)
        self.assertIn("trade_count >= 30", Path(test_opening.__file__).read_text(encoding="utf-8"))
        self.assertIn(test_opening.APPROVAL_PHRASE, memo)
        self.assertEqual(memo.count("python3 -m research.test_opening --frozen-sha"), 1)
        self.assertIn("Secondary diagnostics без влияния на verdict", memo)

    def test_gate_rejects_wrong_phrase_and_short_sha_before_integrity_or_data(self):
        with patch("research.test_opening_integrity.verify_all") as verifier:
            with self.assertRaises(RuntimeError):
                test_opening.verify_gate("wrong", FROZEN_SHA)
            verifier.assert_not_called()
            with self.assertRaises(RuntimeError):
                test_opening.verify_gate(test_opening.APPROVAL_PHRASE, FROZEN_SHA[:7])
            verifier.assert_not_called()

    def test_gate_rejects_existing_sentinel(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / "OPENED_ONCE.json"
            sentinel.write_text("{}", encoding="utf-8")
            with patch.object(test_opening, "SENTINEL", sentinel), \
                 patch.object(test_opening, "RESULT", Path(directory) / "result.json"), \
                 patch("research.test_opening_integrity.verify_all") as verifier:
                with self.assertRaises(RuntimeError):
                    test_opening.verify_gate(test_opening.APPROVAL_PHRASE, FROZEN_SHA)
                verifier.assert_not_called()

    def test_ci95_is_deterministic_and_primary_verdict_is_not_secondary(self):
        values = [float(i) / 10 for i in range(-10, 31)]
        with patch.object(test_opening, "BOOTSTRAP_RESAMPLES", 2000):
            first = test_opening.bootstrap_ci95(values)
            second = test_opening.bootstrap_ci95(values)
        self.assertEqual(first, second)
        source = Path(test_opening.__file__).read_text(encoding="utf-8")
        verdict_expression = "passed = len(values) >= 30 and ci95[0] is not None and ci95[0] > 0"
        self.assertIn(verdict_expression, source)

    def test_safe_verifier_does_not_import_or_execute_test_runner(self):
        source = Path(__import__("research.test_opening_integrity", fromlist=["x"]).__file__).read_text(encoding="utf-8")
        self.assertNotIn("download_symbol", source)
        self.assertNotIn("execute_once", source)


if __name__ == "__main__":
    unittest.main()
