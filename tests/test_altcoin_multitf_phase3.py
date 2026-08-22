from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from research.altcoin_multitf_phase3 import (
    BASE_SLIPPAGE,
    FEE,
    canonical_id,
    evaluate_a,
    frozen_manifest,
    load_daily_panel,
)


class Phase3ManifestTests(unittest.TestCase):
    def test_manifest_is_deterministic_and_complete(self) -> None:
        first, second = frozen_manifest(), frozen_manifest()
        self.assertEqual(first, second)
        family_a = [x for x in first["hypotheses"] if x["family"] == "A"]
        family_b = [x for x in first["hypotheses"] if x["family"] == "B"]
        self.assertEqual(len(family_a), 3060)
        self.assertEqual(len(family_b), 55080)
        self.assertEqual(len({x["config_id"] for x in first["hypotheses"]}), len(first["hypotheses"]))

    def test_canonical_id_ignores_mapping_order(self) -> None:
        self.assertEqual(canonical_id({"a": 1, "b": 2}), canonical_id({"b": 2, "a": 1}))

    def test_holdout_rejected_before_io(self) -> None:
        with self.assertRaisesRegex(ValueError, "holdout"):
            load_daily_panel(Path("missing/holdout"))


class Phase3PortfolioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = pd.date_range("2020-01-01", periods=180, freq="D", tz="UTC")
        self.close = pd.DataFrame({
            "A": np.linspace(100, 200, len(self.index)),
            "B": np.linspace(100, 120, len(self.index)),
            "C": np.linspace(100, 80, len(self.index)),
        }, index=self.index)
        self.opened = self.close.copy()
        self.funds = pd.DataFrame(0.0, index=self.index, columns=self.close.columns)
        self.config = {"config_id": "test", "family": "A", "timeframe": "1d", "lookback_days": 7,
                       "rebalance": "3d", "breadth": "top2", "weighting": "equal", "volatility_target": 0.20}

    def test_next_open_and_costs_are_adverse(self) -> None:
        base, ledger = evaluate_a(self.config, self.close, self.opened, self.funds)
        no_cost, _ = evaluate_a(self.config, self.close, self.opened, self.funds, slippage=-FEE)
        self.assertLessEqual(base["compounded_net_return"], no_cost["compounded_net_return"])
        self.assertTrue((ledger["cost"] >= 0).all())
        self.assertTrue((ledger["gross_exposure"] <= 1.0 + 1e-12).all())

    def test_funding_sign_for_long_position(self) -> None:
        positive_funding = self.funds.copy()
        positive_funding.loc[:, "A"] = 0.001
        funded, _ = evaluate_a(self.config, self.close, self.opened, positive_funding, BASE_SLIPPAGE)
        baseline, _ = evaluate_a(self.config, self.close, self.opened, self.funds, BASE_SLIPPAGE)
        self.assertLess(funded["compounded_net_return"], baseline["compounded_net_return"])

    def test_extra_delay_changes_replay_without_lookahead(self) -> None:
        baseline, _ = evaluate_a(self.config, self.close, self.opened, self.funds)
        delayed, _ = evaluate_a(self.config, self.close, self.opened, self.funds, extra_delay=1)
        self.assertNotEqual(baseline["compounded_net_return"], delayed["compounded_net_return"])


if __name__ == "__main__":
    unittest.main()
