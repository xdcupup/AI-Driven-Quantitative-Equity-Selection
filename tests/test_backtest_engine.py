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


if __name__ == "__main__":
    unittest.main()
