from __future__ import annotations

import unittest

from research.altcoin_multitf_compact import BAR_MS, BoundaryError
from research.altcoin_multitf_phase2 import (
    FROZEN_PARAMETERS,
    Bar,
    EligibilityRun,
    FundingRecord,
    GroupParameters,
    calculate_feature,
    closed_bars,
    generate_signals,
    portfolio_interface,
    timeframe_group,
)

T0 = 1_700_000_000_000


def bars(symbol: str, timeframe: str, count: int, *, step: int = BAR_MS, bump: float = 1.0) -> list[Bar]:
    return [Bar(symbol, timeframe, T0 + i * step, T0 + (i + 1) * step - 1, 100 + i * bump) for i in range(count)]


def eligible(symbol: str, end: int = T0 + 1_000 * BAR_MS) -> EligibilityRun:
    return EligibilityRun(symbol, T0, end, "ge_25m")


class Phase2CausalEngineTests(unittest.TestCase):
    def test_no_future_data(self) -> None:
        history = bars("A", "5m", 60)
        decision = history[50].close_time_ms
        baseline = calculate_feature("A", "5m", decision, history, [])
        mutated = history[:51] + [Bar("A", "5m", row.open_time_ms, row.close_time_ms, row.close * 100) for row in history[51:]]
        self.assertEqual(baseline, calculate_feature("A", "5m", decision, mutated, []))

    def test_higher_timeframe_close_availability(self) -> None:
        rows = bars("A", "1h", 25, step=12 * BAR_MS)
        decision = rows[-1].close_time_ms - 1
        self.assertNotIn(rows[-1], closed_bars(rows, decision_time_ms=decision, timeframe="1h"))
        self.assertIn(rows[-1], closed_bars(rows, decision_time_ms=rows[-1].close_time_ms, timeframe="1h"))

    def test_rolling_window_boundary(self) -> None:
        params = {**FROZEN_PARAMETERS, "short": GroupParameters(2, 2, 3, 1)}
        rows = bars("A", "5m", 4)
        result = calculate_feature("A", "5m", rows[-1].close_time_ms, rows, [], parameters=params)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.momentum, __import__("math").log(rows[-1].close / rows[-3].close))  # type: ignore[union-attr]

    def test_funding_publication_alignment(self) -> None:
        rows = bars("A", "5m", 60)
        decision = rows[-1].close_time_ms
        before = FundingRecord("A", decision, 0.01)
        future = FundingRecord("A", decision + 1, 9.0)
        self.assertEqual(calculate_feature("A", "5m", decision, rows, [before]).funding, calculate_feature("A", "5m", decision, rows, [before, future]).funding)  # type: ignore[union-attr]

    def test_eligibility_before_ranking(self) -> None:
        mapping = {"A": bars("A", "5m", 60, bump=1), "B": bars("B", "5m", 60, bump=10)}
        decision = mapping["A"][-1].close_time_ms
        signals, diagnostics = generate_signals(decision_time_ms=decision, timeframe="5m", bars_by_symbol=mapping, funding=[], eligibility=[eligible("A")])
        self.assertEqual([row.symbol for row in signals], ["A"])
        self.assertEqual(diagnostics.eligible_symbols, 1)

    def test_missing_symbol_handling(self) -> None:
        mapping = {"A": bars("A", "5m", 60), "BTWUSDT": []}
        decision = mapping["A"][-1].close_time_ms
        signals, diagnostics = generate_signals(decision_time_ms=decision, timeframe="5m", bars_by_symbol=mapping, funding=[], eligibility=[eligible("A")])
        self.assertEqual(len(signals), 1)
        self.assertIn("BTWUSDT", diagnostics.excluded_symbols)

    def test_deterministic_output(self) -> None:
        mapping = {name: bars(name, "5m", 60, bump=bump) for name, bump in (("A", 1), ("B", 2))}
        decision = mapping["A"][-1].close_time_ms
        kwargs = dict(decision_time_ms=decision, timeframe="5m", bars_by_symbol=mapping, funding=[], eligibility=[eligible("A"), eligible("B")])
        self.assertEqual(generate_signals(**kwargs), generate_signals(**kwargs))

    def test_symbol_order_invariance(self) -> None:
        a, b = bars("A", "5m", 60), bars("B", "5m", 60, bump=2)
        decision = a[-1].close_time_ms
        common = dict(decision_time_ms=decision, timeframe="5m", funding=[], eligibility=[eligible("A"), eligible("B")])
        self.assertEqual(generate_signals(bars_by_symbol={"A": a, "B": b}, **common), generate_signals(bars_by_symbol={"B": b, "A": a}, **common))

    def test_tf_group_parameter_isolation(self) -> None:
        self.assertEqual(timeframe_group("5m"), "short")
        self.assertEqual(timeframe_group("1h"), "medium")
        self.assertEqual(timeframe_group("1d"), "long")
        changed = {**FROZEN_PARAMETERS, "short": GroupParameters(2, 2, 3, 1)}
        daily = bars("A", "1d", 30, step=288 * BAR_MS)
        decision = daily[-1].close_time_ms
        self.assertEqual(calculate_feature("A", "1d", decision, daily, []), calculate_feature("A", "1d", decision, daily, [], parameters=changed))

    def test_holdout_path_protection(self) -> None:
        with self.assertRaises(BoundaryError):
            generate_signals(decision_time_ms=T0, timeframe="holdout-5m", bars_by_symbol={}, funding=[], eligibility=[])

    def test_portfolio_interface_has_no_execution(self) -> None:
        mapping = {"A": bars("A", "5m", 60)}
        decision = mapping["A"][-1].close_time_ms
        signals, _ = generate_signals(decision_time_ms=decision, timeframe="5m", bars_by_symbol=mapping, funding=[], eligibility=[eligible("A")])
        candidates = portfolio_interface(signals)
        self.assertEqual(candidates[0].symbol, "A")
        self.assertFalse(hasattr(candidates[0], "pnl"))


if __name__ == "__main__":
    unittest.main()
