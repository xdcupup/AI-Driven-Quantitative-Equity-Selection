import unittest

import pandas as pd

from core.astock.fundamental.mootdx_finance import MootdxFinanceClient


class MootdxFinanceClientTest(unittest.TestCase):
    EXPECTED_COLUMNS = [
        "ts_code",
        "ann_date",
        "end_date",
        "eps",
        "bps",
        "roe",
        "roe_waa",
        "profit_yoy",
        "revenue_yoy",
        "free_cashflow",
        "gross_margin",
        "net_margin",
        "dt_debt_ratio",
        "source",
    ]

    def test_fetch_financial_indicators_normalizes_snapshot(self):
        class FakeQuotes:
            def finance(self, symbol):
                self.symbol = symbol
                return pd.DataFrame({
                    "code": ["000001"],
                    "updated_date": [20260425],
                    "zongguben": [100.0],
                    "jinglirun": [20.0],
                    "meigujingzichan": [5.0],
                    "jingzichan": [200.0],
                    "zhuyingshouru": [400.0],
                    "zhuyinglirun": [120.0],
                    "jingyingxianjinliu": [80.0],
                    "zongzichan": [500.0],
                })

        fake = FakeQuotes()
        client = MootdxFinanceClient(quotes=fake)

        result = client.fetch_financial_indicators(
            "000001.SZ", "20260101", "20261231"
        )

        self.assertEqual(fake.symbol, "000001")
        self.assertEqual(list(result.columns), self.EXPECTED_COLUMNS)
        row = result.iloc[0]
        self.assertEqual(row["ts_code"], "000001.SZ")
        self.assertEqual(row["ann_date"], pd.Timestamp("2026-04-25"))
        self.assertEqual(row["end_date"], pd.Timestamp("2026-04-25"))
        self.assertEqual(row["eps"], 0.2)
        self.assertEqual(row["bps"], 5.0)
        self.assertEqual(row["roe"], 10.0)
        self.assertEqual(row["gross_margin"], 30.0)
        self.assertEqual(row["net_margin"], 5.0)
        self.assertEqual(row["dt_debt_ratio"], 60.0)
        self.assertEqual(row["free_cashflow"], 80.0)
        self.assertEqual(row["source"], "mootdx_finance")

    def test_fetch_financial_indicators_filters_date_range_and_handles_errors(self):
        class OldQuotes:
            def finance(self, symbol):
                return pd.DataFrame({
                    "updated_date": [20240101],
                    "zongguben": [100.0],
                    "jinglirun": [20.0],
                })

        empty = MootdxFinanceClient(quotes=OldQuotes()).fetch_financial_indicators(
            "000001.SZ", "20260101", "20261231"
        )

        self.assertTrue(empty.empty)
        self.assertEqual(list(empty.columns), self.EXPECTED_COLUMNS)

        class BrokenQuotes:
            def finance(self, symbol):
                raise RuntimeError("network down")

        broken = MootdxFinanceClient(quotes=BrokenQuotes()).fetch_financial_indicators(
            "000001.SZ", "20260101", "20261231"
        )

        self.assertTrue(broken.empty)
        self.assertEqual(list(broken.columns), self.EXPECTED_COLUMNS)


if __name__ == "__main__":
    unittest.main()
