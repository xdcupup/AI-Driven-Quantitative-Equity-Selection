import unittest

import pandas as pd

from core.data_cleaner import DataCleaner, build_trade_calendar


class DataCleanerTest(unittest.TestCase):
    def setUp(self):
        self.cleaner = DataCleaner({
            "cleaning": {
                "max_daily_pct": 15.0,
                "min_trading_days": 20,
                "outlier_method": "mad",
                "mad_threshold": 5.0,
            }
        })

    def test_cleaning_does_not_clip_prices(self):
        dates = pd.date_range("2026-01-01", periods=20, freq="B")
        closes = [10.0] * 19 + [30.0]
        df = pd.DataFrame({
            "ts_code": ["000001.SZ"] * 20,
            "trade_date": dates,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "vol": [1000.0] * 20,
            "amount": [10000.0] * 20,
        })

        result = self.cleaner.clean_kline(df)

        self.assertEqual(result.iloc[-1]["close"], 30.0)
        self.assertTrue(bool(result.iloc[-1]["flag_extreme"]))
        self.assertFalse(bool(result.iloc[-1]["flag_invalid_ohlc"]))

    def test_calendar_alignment_marks_suspension(self):
        df = pd.DataFrame({
            "ts_code": ["000001.SZ", "000001.SZ"],
            "trade_date": pd.to_datetime(["2026-06-12", "2026-06-16"]),
            "open": [10.0, 11.0],
            "high": [10.5, 11.5],
            "low": [9.5, 10.5],
            "close": [10.0, 11.0],
            "vol": [1000.0, 1200.0],
            "amount": [10000.0, 13000.0],
        })
        calendar = pd.DatetimeIndex(pd.to_datetime([
            "2026-06-12", "2026-06-15", "2026-06-16"
        ]))

        result = self.cleaner.clean_kline(df, calendar)
        aligned = result[result["trade_date"] == pd.Timestamp("2026-06-15")].iloc[0]

        self.assertTrue(bool(aligned["flag_aligned"]))
        self.assertTrue(bool(aligned["flag_suspended"]))
        self.assertEqual(aligned["vol"], 0.0)
        self.assertEqual(aligned["pct_chg"], 0.0)
        self.assertEqual(aligned["ts_code"], "000001.SZ")

    def test_adjustment_formula_names_are_correct(self):
        prices = pd.DataFrame({
            "trade_date": pd.to_datetime(["2026-06-12", "2026-06-16"]),
            "open": [10.0, 11.0],
            "high": [10.0, 11.0],
            "low": [10.0, 11.0],
            "close": [10.0, 11.0],
        })
        factors = pd.DataFrame({
            "trade_date": pd.to_datetime(["2026-06-12", "2026-06-16"]),
            "adj_factor": [1.0, 2.0],
        })

        qfq = self.cleaner.adjust_price(prices.copy(), factors, "qfq")
        hfq = self.cleaner.adjust_price(prices.copy(), factors, "hfq")

        self.assertEqual(qfq["adj_close"].tolist(), [5.0, 11.0])
        self.assertEqual(hfq["adj_close"].tolist(), [10.0, 22.0])

    def test_unknown_amount_is_not_converted_to_zero(self):
        df = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": pd.to_datetime(["2026-06-15"]),
            "open": [10.0],
            "high": [10.5],
            "low": [9.8],
            "close": [10.2],
            "vol": [1000.0],
            "amount": [float("nan")],
        })

        result = self.cleaner.clean_kline(df)

        self.assertTrue(pd.isna(result.iloc[0]["amount"]))

    def test_build_trade_calendar_uses_config_date_range(self):
        class FakeFetcher:
            def __init__(self):
                self.years = []

            def fetch_trade_calendar(self, year):
                self.years.append(year)
                return pd.DataFrame({
                    "trade_date": pd.to_datetime([f"{year}-01-02"]),
                    "is_open": [1],
                })

        fetcher = FakeFetcher()
        result = build_trade_calendar(
            fetcher,
            {"fetch": {"start_date": "20200101", "end_date": "20260616"}},
        )

        self.assertEqual(fetcher.years, [2020, 2021, 2022, 2023, 2024, 2025, 2026])
        self.assertEqual(len(result), 7)


if __name__ == "__main__":
    unittest.main()
