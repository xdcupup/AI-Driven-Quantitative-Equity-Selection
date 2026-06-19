import unittest

import pandas as pd

from core.factors.technical import derive_technical_factors


class TechnicalFactorDerivationTest(unittest.TestCase):
    def test_derives_core_technical_factors_from_daily_kline(self):
        dates = pd.date_range("2026-01-01", periods=70, freq="B")
        close = [100.0 + i for i in range(70)]
        vol = [1000.0 + i * 10 for i in range(70)]
        amount = [close[i] * vol[i] for i in range(70)]
        kline = pd.DataFrame({
            "ts_code": ["000001.SZ"] * 70,
            "trade_date": dates,
            "close": close,
            "vol": vol,
            "amount": amount,
        })

        result = derive_technical_factors(kline)

        row = result.iloc[-1]
        self.assertEqual(row["ts_code"], "000001.SZ")
        self.assertEqual(row["trade_date"], dates[-1])
        self.assertAlmostEqual(row["return_5d"], (169.0 / 164.0 - 1) * 100)
        self.assertAlmostEqual(row["return_20d"], (169.0 / 149.0 - 1) * 100)
        self.assertAlmostEqual(row["return_60d"], (169.0 / 109.0 - 1) * 100)
        self.assertGreater(row["volatility_20d"], 0)
        self.assertAlmostEqual(row["ma20_bias"], (169.0 / pd.Series(close[-20:]).mean() - 1) * 100)
        self.assertAlmostEqual(row["ma60_bias"], (169.0 / pd.Series(close[-60:]).mean() - 1) * 100)
        self.assertEqual(row["max_drawdown_60d"], 0.0)
        self.assertAlmostEqual(row["volume_ratio_20d"], vol[-1] / pd.Series(vol[-20:]).mean())
        self.assertAlmostEqual(row["liquidity_20d"], pd.Series(amount[-20:]).mean())
        self.assertEqual(row["source"], "daily_kline")

    def test_empty_input_returns_stable_schema(self):
        result = derive_technical_factors(pd.DataFrame())

        self.assertTrue(result.empty)
        self.assertIn("return_20d", result.columns)


if __name__ == "__main__":
    unittest.main()
