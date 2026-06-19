import unittest
from unittest.mock import Mock

from core.astock.eastmoney.dragon_tiger import fetch_dragon_tiger


class DragonTigerTest(unittest.TestCase):
    def test_returns_empty_for_empty_response(self):
        client = Mock()
        client.datacenter.return_value = []
        result = fetch_dragon_tiger(client, "000001.SZ", "2026-06-19")
        self.assertTrue(result.empty)
        self.assertEqual(
            list(result.columns),
            ["ts_code", "trade_date", "buy_amount", "sell_amount",
             "net_amount", "reason", "source"],
        )

    def test_parses_datacenter_response(self):
        client = Mock()
        client.datacenter.return_value = [
            {
                "SECURITY_CODE": "000001.SZ", "TRADE_DATE": "2026-06-19 00:00:00",
                "BUY_AMT": 50000000.0, "SELL_AMT": 30000000.0,
                "NET_AMT": 20000000.0, "REASON": "日涨幅偏离值达7%",
            },
        ]
        result = fetch_dragon_tiger(client, "000001.SZ", "2026-06-19")
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result.iloc[0]["buy_amount"], 50000000.0)
        self.assertAlmostEqual(result.iloc[0]["net_amount"], 20000000.0)
        self.assertEqual(result.iloc[0]["reason"], "日涨幅偏离值达7%")
        self.assertEqual(result.iloc[0]["source"], "eastmoney_dragon_tiger")


if __name__ == "__main__":
    unittest.main()
