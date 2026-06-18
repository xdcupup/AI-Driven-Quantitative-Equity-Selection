import unittest

import pandas as pd

from core.factors.financial import derive_financial_factors


class FinancialFactorDerivationTest(unittest.TestCase):
    def test_derives_core_factors_from_statement_items(self):
        statements = pd.DataFrame({
            "ts_code": ["000001.SZ"] * 12,
            "report_type": [
                "income_statement",
                "income_statement",
                "balance_sheet",
                "balance_sheet",
                "balance_sheet",
                "cash_flow",
            ] * 2,
            "end_date": pd.to_datetime(["2026-03-31"] * 6 + ["2025-03-31"] * 6),
            "ann_date": [pd.NaT] * 12,
            "item_order": list(range(1, 7)) * 2,
            "item": [
                "营业总收入",
                "净利润",
                "资产总计",
                "负债合计",
                "所有者权益合计",
                "经营活动产生的现金流量净额",
                "营业总收入",
                "净利润",
                "资产总计",
                "负债合计",
                "所有者权益合计",
                "经营活动产生的现金流量净额",
            ],
            "value": [
                120.0,
                24.0,
                500.0,
                300.0,
                200.0,
                30.0,
                100.0,
                20.0,
                400.0,
                260.0,
                140.0,
                15.0,
            ],
            "source": ["sina_finance"] * 12,
        })

        result = derive_financial_factors(statements)

        current = result[result["end_date"] == pd.Timestamp("2026-03-31")].iloc[0]
        self.assertEqual(current["ts_code"], "000001.SZ")
        self.assertEqual(current["revenue"], 120.0)
        self.assertEqual(current["net_profit"], 24.0)
        self.assertEqual(current["total_assets"], 500.0)
        self.assertEqual(current["total_liabilities"], 300.0)
        self.assertEqual(current["equity"], 200.0)
        self.assertEqual(current["operating_cashflow"], 30.0)
        self.assertEqual(current["revenue_yoy"], 20.0)
        self.assertEqual(current["net_profit_yoy"], 20.0)
        self.assertEqual(current["debt_to_assets"], 60.0)
        self.assertEqual(current["roe"], 12.0)
        self.assertEqual(current["operating_cashflow_to_profit"], 1.25)
        self.assertEqual(current["source"], "financial_statements")

    def test_empty_input_returns_stable_schema(self):
        result = derive_financial_factors(pd.DataFrame())

        self.assertTrue(result.empty)
        self.assertIn("revenue_yoy", result.columns)


if __name__ == "__main__":
    unittest.main()
