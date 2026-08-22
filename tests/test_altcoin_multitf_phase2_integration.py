import json
import tempfile
import unittest
from pathlib import Path

from research.altcoin_multitf_phase2 import PortfolioCandidate
from research.altcoin_multitf_phase2_dataset import (
    PROTOCOL_ID,
    load_development_slice,
    run_integration,
)

DATASET = Path("data/altcoin-multitf-005")
EXPECTED_MANIFEST_SHA256 = "9541bad8793b584f74754828f4abb762e1a75dbfdbb8ae823d3256c9049ce0cf"


class Phase2DatasetContractTests(unittest.TestCase):
    def test_holdout_path_rejected_before_io(self):
        with self.assertRaisesRegex(ValueError, "holdout"):
            load_development_slice(Path("does-not-exist/holdout"), "5m", 0)
        with self.assertRaisesRegex(ValueError, "holdout"):
            load_development_slice(Path("does-not-exist"), "holdout-5m", 0)

    def test_portfolio_candidate_is_schema_only(self):
        self.assertEqual(
            set(PortfolioCandidate.__dataclass_fields__),
            {"symbol", "timeframe", "decision_time_ms", "score", "rank", "direction"},
        )


@unittest.skipUnless(DATASET.exists(), "restored ALT-MULTITF-005 required")
class Phase2RealDataIntegrationTests(unittest.TestCase):
    def test_real_loader_schema_and_missing_btw(self):
        loaded = load_development_slice(DATASET, "1d", 1767225599999)
        self.assertEqual(loaded.protocol_id, PROTOCOL_ID)
        self.assertEqual(loaded.manifest_sha256, EXPECTED_MANIFEST_SHA256)
        self.assertEqual(len(loaded.roster), 40)
        self.assertIn("BTWUSDT", loaded.roster)
        self.assertEqual(loaded.bars_by_symbol["BTWUSDT"], ())
        self.assertTrue(all(bar.close_time_ms <= 1767225599999 for bars in loaded.bars_by_symbol.values() for bar in bars))
        self.assertTrue(all(item.publication_time_ms <= 1767225599999 for item in loaded.funding))

    def test_real_integration_digest_is_deterministic(self):
        first = run_integration(DATASET)
        second = run_integration(DATASET)
        self.assertEqual(first, second)
        self.assertEqual(first["input_manifest_sha256"], EXPECTED_MANIFEST_SHA256)
        self.assertEqual({item["timeframe"] for item in first["checks"]}, {"5m", "1h", "1d"})
        forbidden = {"pnl", "returns", "sharpe", "sortino", "drawdown", "weight", "order", "trade"}
        self.assertFalse(forbidden.intersection(json.dumps(first).lower().replace('"', " ").split()))


if __name__ == "__main__":
    unittest.main()
