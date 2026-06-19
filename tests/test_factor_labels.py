import unittest

import pandas as pd

from core.factors.labels import derive_forward_return_labels


class FactorLabelDerivationTest(unittest.TestCase):
    def test_derives_forward_returns_and_drawdown_from_future_prices(self):
        dates = pd.date_range("2026-01-01", periods=30, freq="B")
        close = [100.0 + i for i in range(30)]
        kline = pd.DataFrame({
            "ts_code": ["000001.SZ"] * 30,
            "trade_date": dates,
            "close": close,
        })

        result = derive_forward_return_labels(kline, horizons=(5, 10), drawdown_horizon=10)

        first = result.iloc[0]
        self.assertEqual(first["ts_code"], "000001.SZ")
        self.assertEqual(first["trade_date"], dates[0])
        self.assertAlmostEqual(first["forward_return_5d"], (105.0 / 100.0 - 1) * 100)
        self.assertAlmostEqual(first["forward_return_10d"], (110.0 / 100.0 - 1) * 100)
        self.assertEqual(first["max_drawdown_10d"], 0.0)
        self.assertEqual(first["source"], "daily_kline")
        self.assertTrue(pd.isna(result.iloc[-1]["forward_return_5d"]))

    def test_empty_input_returns_stable_schema(self):
        result = derive_forward_return_labels(pd.DataFrame(), horizons=(5, 20))

        self.assertTrue(result.empty)
        self.assertIn("forward_return_20d", result.columns)


if __name__ == "__main__":
    unittest.main()
