import unittest

import pandas as pd

from core.astock.fundamental.mootdx_finance import MootdxFinanceClient
from core.astock.fundamental.mootdx_f10 import MootdxF10Client
from core.astock.fundamental.sina_finance import SinaFinancialStatementClient


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


class SinaFinancialStatementClientTest(unittest.TestCase):
    EXPECTED_COLUMNS = [
        "ts_code",
        "report_type",
        "end_date",
        "ann_date",
        "item_order",
        "item",
        "value",
        "item_yoy",
        "source",
    ]

    def test_fetch_statement_expands_report_list_items(self):
        class FakeResponse:
            status_code = 200

            def json(self):
                return {
                    "result": {
                        "data": {
                            "report_list": {
                                "20260331": {
                                    "data": [
                                        {
                                            "item_title": "营业总收入",
                                            "item_value": "100.5",
                                            "item_tongbi": "8.2",
                                        },
                                        {
                                            "item_title": "空值项",
                                            "item_value": None,
                                        },
                                    ]
                                },
                                "20251231": {
                                    "data": [
                                        {
                                            "item_title": "营业总收入",
                                            "item_value": "90.0",
                                            "item_tongbi": "",
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }

        class FakeSession:
            def get(self, url, params, headers, timeout):
                self.params = params
                return FakeResponse()

        session = FakeSession()
        client = SinaFinancialStatementClient(session=session)

        result = client.fetch_statement(
            "000001.SZ", "income_statement", "20260101", "20261231"
        )

        self.assertEqual(session.params["paperCode"], "sz000001")
        self.assertEqual(session.params["source"], "lrb")
        self.assertEqual(list(result.columns), self.EXPECTED_COLUMNS)
        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        self.assertEqual(row["ts_code"], "000001.SZ")
        self.assertEqual(row["report_type"], "income_statement")
        self.assertEqual(row["end_date"], pd.Timestamp("2026-03-31"))
        self.assertTrue(pd.isna(row["ann_date"]))
        self.assertEqual(row["item_order"], 1)
        self.assertEqual(row["item"], "营业总收入")
        self.assertEqual(row["value"], 100.5)
        self.assertEqual(row["item_yoy"], 8.2)
        self.assertEqual(row["source"], "sina_finance")

    def test_fetch_statement_supports_aliases_and_non_numeric_values(self):
        class FakeResponse:
            status_code = 200

            def json(self):
                return {
                    "result": {
                        "data": {
                            "report_list": {
                                "20260331": {
                                    "data": [
                                        {
                                            "item_title": "审计意见",
                                            "item_value": "标准无保留意见",
                                        }
                                    ]
                                }
                            }
                        }
                    }
                }

        class FakeSession:
            def get(self, url, params, headers, timeout):
                self.params = params
                return FakeResponse()

        session = FakeSession()
        client = SinaFinancialStatementClient(session=session)

        result = client.fetch_statement("600519.SH", "fzb", "20260101", "20261231")

        self.assertEqual(session.params["paperCode"], "sh600519")
        self.assertEqual(session.params["source"], "fzb")
        self.assertEqual(result.iloc[0]["report_type"], "balance_sheet")
        self.assertEqual(result.iloc[0]["value"], "标准无保留意见")

    def test_fetch_statement_errors_return_stable_empty_schema(self):
        class BrokenSession:
            def get(self, url, params, headers, timeout):
                raise RuntimeError("network down")

        client = SinaFinancialStatementClient(session=BrokenSession())

        result = client.fetch_statement("000001.SZ", "cash_flow", "20260101", "20261231")

        self.assertTrue(result.empty)
        self.assertEqual(list(result.columns), self.EXPECTED_COLUMNS)


if __name__ == "__main__":
    unittest.main()
