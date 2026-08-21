from __future__ import annotations

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from research.altcoin_basket_data import HoldoutSealedError
from research.altcoin_basket_postmortem import diagnose, load_ledger


FIELDS = ["decision_iso", "status", "reason", "eligible_count", "eligible", "symbol", "side", "weight", "entry_iso", "exit_iso", "entry_price", "exit_price", "leg_gross_return", "leg_funding_return", "momentum", "volatility", "period_net_return"]


def row(symbol="ETHUSDT", side=1, weight=0.5, gross=0.02, funding=-0.001, net=0.0088):
    return {"decision_iso": "2025-01-01T00:00:00Z", "status": "active", "reason": "", "eligible_count": "10", "eligible": "", "symbol": symbol, "side": str(side), "weight": str(weight), "entry_iso": "2025-01-01T00:00:00Z", "exit_iso": "2025-01-02T00:00:00Z", "entry_price": "1", "exit_price": "1", "leg_gross_return": str(gross), "leg_funding_return": str(funding), "momentum": "0", "volatility": "0.01", "period_net_return": str(net)}


class TestPostmortem(unittest.TestCase):
    def test_decomposition_legs_symbols_costs_and_concentration(self):
        rows = [row(), row("BNBUSDT", -1, 0.5, 0.0, 0.0)]
        result = diagnose(rows)
        self.assertAlmostEqual(result["gross_return_sum"], 0.01)
        self.assertAlmostEqual(result["funding_return_sum"], -0.0005)
        self.assertAlmostEqual(result["cost_drag"], 0.0012)
        self.assertAlmostEqual(result["net_return_sum"], 0.0083)
        self.assertAlmostEqual(result["legs"]["long"]["net"], 0.0089)
        self.assertAlmostEqual(result["legs"]["short"]["net"], -0.0006)
        self.assertEqual(result["concentration"]["breach_periods"], 1)
        self.assertEqual(result["missing_funding_observations"], 0)
        self.assertAlmostEqual(sum(x["net"] for x in result["symbols"].values()), result["net_return_sum"])

    def test_period_reconciliation_rejects_bad_total(self):
        with self.assertRaises(ValueError):
            diagnose([row(net=99), row("BNBUSDT", -1, 0.5, 0.0, 0.0, net=99)])

    def test_holdout_guard_rejects_boundary(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.csv"
            bad = row(); bad["decision_iso"] = "2026-01-01T00:00:00Z"; bad["entry_iso"] = bad["decision_iso"]
            with path.open("w", newline="") as f:
                writer = csv.DictWriter(f, FIELDS); writer.writeheader(); writer.writerow(bad)
            with self.assertRaises(HoldoutSealedError):
                load_ledger(path)

    def test_output_is_deterministic(self):
        rows = [row(), row("BNBUSDT", -1, 0.5, 0.0, 0.0)]
        self.assertEqual(diagnose(rows), diagnose(reversed(rows)))


if __name__ == "__main__":
    unittest.main()
