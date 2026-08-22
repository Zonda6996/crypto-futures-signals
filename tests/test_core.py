import unittest

from research.core import (
    Bar,
    CostModel,
    ExitRules,
    assert_selection_indices,
    backward_asof,
    chronological_splits,
    forward_return_target,
    simulate_trade,
)


def bars(prices):
    return [Bar(i * 3_600_000, p, p + 1, p - 1, p + 0.5, 10, 5) for i, p in enumerate(prices)]


class CausalityTests(unittest.TestCase):
    def test_target_uses_next_open(self):
        data = bars([100, 110, 120, 130])
        target = forward_return_target(data, horizon=1)
        self.assertAlmostEqual(target[0], 120 / 110 - 1)
        self.assertIsNone(target[-2])

    def test_prefix_invariance(self):
        prefix = bars([100, 101, 102, 103])
        extended = bars([100, 101, 102, 103, 999])
        self.assertEqual(forward_return_target(prefix, 1)[:2], forward_return_target(extended, 1)[:2])

    def test_test_split_is_sealed(self):
        splits = chronological_splits(10)
        assert_selection_indices([0, 5, 7], splits)
        with self.assertRaises(RuntimeError):
            assert_selection_indices([8], splits)

    def test_asof_never_uses_future_observation(self):
        values = backward_asof([10, 20, 30], [(15, 1.0), (25, 2.0)])
        self.assertEqual(values, [None, 1.0, 2.0])
        lagged = backward_asof([20], [(15, 1.0)], lag_ms=10)
        self.assertEqual(lagged, [None])


class ExecutionTests(unittest.TestCase):
    def test_long_short_and_costs(self):
        data = bars([100, 100, 110])
        costs = CostModel(taker_fee_bps=5, half_spread_bps=1, slippage_bps=2)
        rules = ExitRules(max_bars=1)
        long = simulate_trade(data, 0, 1, 1, rules, costs)
        short = simulate_trade(data, 0, -1, 1, rules, costs)
        self.assertEqual(long.entry_ts, data[1].ts)
        self.assertAlmostEqual(long.cost_return, 0.0016)
        self.assertGreater(long.net_return, 0)
        self.assertLess(short.net_return, 0)

    def test_funding_cash_flow_sign(self):
        data = bars([100, 100, 100])
        funding = {data[1].ts: 0.001}
        rules = ExitRules(max_bars=1)
        zero_cost = CostModel(0, 0, 0)
        long = simulate_trade(data, 0, 1, 1, rules, zero_cost, funding)
        short = simulate_trade(data, 0, -1, 1, rules, zero_cost, funding)
        self.assertAlmostEqual(long.funding_return, -0.001)
        self.assertAlmostEqual(short.funding_return, 0.001)

    def test_stop_wins_same_bar_collision(self):
        data = [Bar(0, 100, 100, 100, 100, 1), Bar(1, 100, 110, 90, 100, 1)]
        trade = simulate_trade(data, 0, 1, 5, ExitRules(1, stop_atr=1, take_atr=1), CostModel(0, 0, 0))
        self.assertEqual(trade.exit_reason, "stop")
        self.assertEqual(trade.exit, 95)


if __name__ == "__main__":
    unittest.main()
