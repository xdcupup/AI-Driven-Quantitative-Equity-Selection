import unittest

import pandas as pd

from core.astock.fundamental.mootdx_finance import MootdxFinanceClient
from core.astock.fundamental.mootdx_f10 import MootdxF10Client


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


class MootdxF10ClientTest(unittest.TestCase):
    CATEGORY_COLUMNS = [
        "ts_code",
        "name",
        "filename",
        "start",
        "length",
        "source",
    ]

    def test_fetch_categories_normalizes_directory(self):
        class FakeQuotes:
            def F10C(self, symbol):
                self.symbol = symbol
                return [
                    {"name": "公司概况", "filename": "000001.txt", "start": 10, "length": 20},
                    {"name": "股本结构", "filename": "000001.txt", "start": 30, "length": 40},
                ]

        fake = FakeQuotes()
        client = MootdxF10Client(quotes=fake)

        result = client.fetch_categories("000001.SZ")

        self.assertEqual(fake.symbol, "000001")
        self.assertEqual(list(result.columns), self.CATEGORY_COLUMNS)
        self.assertEqual(result["name"].tolist(), ["公司概况", "股本结构"])
        self.assertEqual(result["ts_code"].unique().tolist(), ["000001.SZ"])
        self.assertEqual(result["source"].unique().tolist(), ["mootdx_f10"])

    def test_fetch_section_returns_stable_record_and_handles_missing(self):
        class FakeQuotes:
            def F10(self, symbol, name):
                self.call = (symbol, name)
                if name == "公司概况":
                    return "☆公司概况☆\n平安银行股份有限公司"
                return None

        fake = FakeQuotes()
        client = MootdxF10Client(quotes=fake)

        result = client.fetch_section("000001.SZ", "公司概况")

        self.assertEqual(fake.call, ("000001", "公司概况"))
        self.assertEqual(result["ts_code"], "000001.SZ")
        self.assertEqual(result["section"], "公司概况")
        self.assertIn("平安银行", result["content"])
        self.assertEqual(result["source"], "mootdx_f10")

        missing = client.fetch_section("000001.SZ", "不存在")
        self.assertEqual(missing["content"], "")
        self.assertEqual(missing["source"], "mootdx_f10")

    def test_f10_errors_return_stable_empty_values(self):
        class BrokenQuotes:
            def F10C(self, symbol):
                raise RuntimeError("network down")

            def F10(self, symbol, name):
                raise RuntimeError("network down")

        client = MootdxF10Client(quotes=BrokenQuotes())

        categories = client.fetch_categories("000001.SZ")
        section = client.fetch_section("000001.SZ", "公司概况")

        self.assertTrue(categories.empty)
        self.assertEqual(list(categories.columns), self.CATEGORY_COLUMNS)
        self.assertEqual(section["content"], "")
        self.assertEqual(section["error"], "network down")


if __name__ == "__main__":
    unittest.main()
