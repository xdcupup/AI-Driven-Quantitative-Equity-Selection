"""Tests for backtest engine — core logic for factor-based backtesting."""

import unittest

import numpy as np
import pandas as pd

from core.backtest.config import BacktestConfig
from core.backtest.engine import BacktestEngine


class BacktestEngineTest(unittest.TestCase):
    def setUp(self):
        self.config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
            top_n=5,
            bottom_n=5,
        )

    def test_engine_initializes_with_config(self):
        engine = BacktestEngine(self.config)
        self.assertEqual(engine.config.top_n, 5)
        self.assertEqual(engine.config.initial_capital, 1_000_000.0)

    def test_engine_returns_empty_result_for_empty_data(self):
        engine = BacktestEngine(self.config)
        result = engine.run(
            factors=pd.DataFrame(),
            labels=pd.DataFrame(),
            kline=pd.DataFrame(),
        )
        self.assertEqual(result["total_return"], 0.0)
        self.assertEqual(result["sharpe_ratio"], 0.0)
        self.assertEqual(len(result["daily_returns"]), 0)

    def test_score_stocks_ranks_by_factor_zscore_sum(self):
        engine = BacktestEngine(self.config)
        factors = pd.DataFrame({
            "ts_code": ["A", "B", "C", "D", "E"],
            "trade_date": pd.Timestamp("2024-01-02"),
            "return_20d": [0.01, 0.05, -0.02, 0.10, 0.03],
            "volatility_20d": [0.15, 0.20, 0.10, 0.25, 0.18],
        })
        # Only use return_20d for scoring
        engine.config.factor_columns = ["return_20d", "volatility_20d"]
        scored = engine._score_stocks(factors)
        self.assertIn("_score", scored.columns)
        # Best return_20d + low vol should rank high
        self.assertEqual(scored.iloc[0]["ts_code"], "D")  # 0.10 return

    def test_rebalance_selects_top_n_stocks(self):
        engine = BacktestEngine(self.config)
        engine.config.top_n = 2
        factors = pd.DataFrame({
            "ts_code": ["A", "B", "C"],
            "trade_date": pd.Timestamp("2024-01-02"),
            "return_20d": [0.01, 0.05, -0.02],
            "volatility_20d": [0.15, 0.20, 0.10],
        })
        engine.config.factor_columns = ["return_20d", "volatility_20d"]
        engine._rebalance(factors, pd.Timestamp("2024-01-02"))
        # Should have 2 positions max
        self.assertLessEqual(len(engine.portfolio.positions), 2)

    def test_portfolio_initializes_with_cash(self):
        from core.backtest.portfolio import Portfolio
        p = Portfolio(1_000_000.0)
        self.assertEqual(p.nav, 1_000_000.0)
        self.assertEqual(p.cash, 1_000_000.0)
        self.assertEqual(len(p.positions), 0)

    def test_portfolio_rebalance_adds_equal_weight_positions(self):
        from core.backtest.portfolio import Portfolio
        p = Portfolio(1_000_000.0)
        p.rebalance(
            target_stocks=["000001.SZ", "000002.SZ"],
            signal_date=pd.Timestamp("2024-01-02"),
            max_positions=10,
            position_sizing="equal_weight",
            turnover_limit=1.0,
        )
        self.assertEqual(len(p.positions), 2)
        self.assertAlmostEqual(sum(pos.weight for pos in p.positions.values()), 1.0)

    def test_portfolio_mark_to_market_updates_nav(self):
        from core.backtest.portfolio import Portfolio
        p = Portfolio(1_000_000.0)
        p.rebalance(
            target_stocks=["000001.SZ"],
            signal_date=pd.Timestamp("2024-01-02"),
            max_positions=10,
            position_sizing="equal_weight",
            turnover_limit=1.0,
        )
        kline = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime(["2024-01-03"]),
            "open": [10.0],
            "close": [10.5],
        })
        p.mark_to_market(kline, pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03"), [])
        # Should have bought shares at ~10.0 with 1M allocated
        pos = p.positions["000001.SZ"]
        self.assertGreater(pos.shares, 0)
        self.assertLess(p.cash, 1_000_000.0)

    def test_compute_metrics_returns_zero_for_empty(self):
        from core.backtest.analytics import compute_metrics
        from core.backtest.config import BacktestConfig
        cfg = BacktestConfig()
        result = compute_metrics([], [], cfg)
        self.assertEqual(result["sharpe_ratio"], 0.0)
        self.assertEqual(result["total_return"], 0.0)

    def test_compute_metrics_calculates_sharpe_from_returns(self):
        from core.backtest.analytics import compute_metrics
        from core.backtest.config import BacktestConfig
        cfg = BacktestConfig()
        returns = [
            {"signal_date": pd.Timestamp("2024-01-02"), "exec_date": pd.Timestamp("2024-01-03"), "daily_return": 0.01, "nav": 1_010_000.0},
            {"signal_date": pd.Timestamp("2024-01-03"), "exec_date": pd.Timestamp("2024-01-04"), "daily_return": -0.005, "nav": 1_004_950.0},
        ]
        result = compute_metrics(returns, [], cfg)
        self.assertAlmostEqual(result["total_return"], 0.00495, places=4)
        self.assertTrue(result["sharpe_ratio"] != 0.0)

    def test_layer_analysis_computes_group_returns(self):
        from core.backtest.analytics import compute_layer_returns
        factors = pd.DataFrame({
            "ts_code": ["A", "B", "C", "D", "E"] * 3,
            "trade_date": pd.to_datetime(["2024-01-02"] * 5 + ["2024-01-03"] * 5 + ["2024-01-04"] * 5),
            "return_20d": [0.01, 0.02, 0.03, 0.04, 0.05] * 3,
        })
        labels = pd.DataFrame({
            "ts_code": ["A", "B", "C", "D", "E"] * 3,
            "trade_date": pd.to_datetime(["2024-01-02"] * 5 + ["2024-01-03"] * 5 + ["2024-01-04"] * 5),
            "forward_return_20d": [0.01, 0.03, 0.05, 0.08, 0.10] * 3,
        })
        result = compute_layer_returns(factors, labels, "return_20d", "forward_return_20d", n_groups=3)
        self.assertIn("groups", result)
        self.assertIn("spread", result)
        # Top group should have higher factor value and return
        self.assertGreater(result["spread"], 0)


if __name__ == "__main__":
    unittest.main()
