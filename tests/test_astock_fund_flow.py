import unittest
from unittest.mock import Mock

import pandas as pd

from core.astock.eastmoney.fund_flow import fetch_stock_fund_flow


class FundFlowTest(unittest.TestCase):
    def test_parses_push2his_history_response(self):
        response = Mock()
        response.json.return_value = {
            "rc": 0,
            "data": {
                "klines": [
                    "2026-06-18,100000000.0,-20000000.0,-30000000.0,50000000.0,50000000.0,5.2,-1.0,-1.5,2.6,2.6,10.50,3.0,0.00,0.00",
                ]
            },
        }
        client = Mock()
        client.em_get.return_value = response
        client.datacenter.return_value = []

        result = fetch_stock_fund_flow(client, "000001.SZ", "2026-06-18")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["trade_date"], pd.Timestamp("2026-06-18"))
        self.assertAlmostEqual(result.iloc[0]["main_net_amt"], 100000000.0)
        self.assertAlmostEqual(result.iloc[0]["main_net_ratio"], 5.2)
        self.assertAlmostEqual(result.iloc[0]["big_net_amt"], 50000000.0)
        self.assertAlmostEqual(result.iloc[0]["huge_net_amt"], 50000000.0)
        self.assertAlmostEqual(result.iloc[0]["ddx"], 0.52)
        self.assertAlmostEqual(result.iloc[0]["ddy"], 0.52)
        self.assertEqual(result.iloc[0]["source"], "eastmoney_fund_flow")

    def test_returns_empty_for_empty_response(self):
        client = Mock()
        client.datacenter.return_value = []
        client.em_get.return_value.json.return_value = {"rc": 0, "data": {"klines": []}}
        result = fetch_stock_fund_flow(client, "000001.SZ", "2026-06-19")
        self.assertTrue(result.empty)

    def test_parses_ddx_ddy_and_flow_fields(self):
        client = Mock()
        client.datacenter.return_value = [
            {
                "SECURITY_CODE": "000001.SZ", "TRADE_DATE": "2026-06-19 00:00:00",
                "MAIN_NET_AMT": 1.5e8, "MAIN_NET_RATIO": 5.2,
                "HUGE_NET_AMT": 8e7, "BIG_NET_AMT": 7e7,
                "MID_NET_AMT": -3e7, "SMALL_NET_AMT": -1.2e8,
                "DDX": 0.75, "DDY": 0.62,
            },
        ]
        result = fetch_stock_fund_flow(client, "000001.SZ", "2026-06-19")
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result.iloc[0]["main_net_amt"], 1.5e8)
        self.assertAlmostEqual(result.iloc[0]["ddx"], 0.75)
        self.assertAlmostEqual(result.iloc[0]["ddy"], 0.62)
        self.assertEqual(result.iloc[0]["source"], "eastmoney_fund_flow")


if __name__ == "__main__":
    unittest.main()
