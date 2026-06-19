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


if __name__ == "__main__":
    unittest.main()
