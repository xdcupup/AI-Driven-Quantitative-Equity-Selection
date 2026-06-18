import unittest
from unittest.mock import Mock

import pandas as pd

from core.astock.market.tencent_quote import TencentQuoteClient


class TencentQuoteClientTest(unittest.TestCase):
    def test_parse_gbk_quote_uses_correct_pb_index(self):
        raw = (
            'v_sh600519="1~贵州茅台~600519~1688.00~1670.00~1678.00~'
            '0~0~0~1687.00~1~1686.00~2~1685.00~3~1689.00~1~1690.00~2~'
            '1691.00~3~0~0~0~0~0~0~0~0~0~0~18.00~1.08~1699.00~1660.00~'
            '0~0~123456.78~2.50~25.60~0~0~0~3.10~21000.00~20000.00~'
            '8.70~1837.80~1502.20~1.20~22.30";'
        ).encode("gbk")
        opener = Mock(return_value=raw)
        client = TencentQuoteClient(opener=opener)

        result = client.fetch_quotes(["600519"])

        row = result.iloc[0]
        self.assertEqual(row["ts_code"], "600519.SH")
        self.assertEqual(row["name"], "贵州茅台")
        self.assertEqual(row["price"], 1688.00)
        self.assertEqual(row["pe_ttm"], 25.60)
        self.assertEqual(row["pb"], 8.70)
        self.assertEqual(row["amount"], 1234567800.0)
        self.assertEqual(row["total_mv"], 2100000000000.0)
        self.assertEqual(row["circ_mv"], 2000000000000.0)


if __name__ == "__main__":
    unittest.main()
