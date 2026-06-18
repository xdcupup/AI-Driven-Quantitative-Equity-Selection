import unittest
from unittest.mock import Mock

import pandas as pd

from core.astock.market.tencent_quote import TencentQuoteClient
from core.astock.market.baidu_kline import BaiduKlineClient


class TencentQuoteClientTest(unittest.TestCase):
    EXPECTED_COLUMNS = [
        "ts_code",
        "symbol",
        "name",
        "price",
        "last_close",
        "open",
        "change_amt",
        "change_pct",
        "high",
        "low",
        "amount",
        "turnover_rate",
        "pe_ttm",
        "amplitude_pct",
        "total_mv",
        "circ_mv",
        "pb",
        "limit_up",
        "limit_down",
        "volume_ratio",
        "pe_static",
        "source",
    ]

    def assertStableColumns(self, result):
        self.assertEqual(list(result.columns), self.EXPECTED_COLUMNS)

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

        self.assertStableColumns(result)
        row = result.iloc[0]
        self.assertEqual(row["ts_code"], "600519.SH")
        self.assertEqual(row["name"], "贵州茅台")
        self.assertEqual(row["price"], 1688.00)
        self.assertEqual(row["pe_ttm"], 25.60)
        self.assertEqual(row["pb"], 8.70)
        self.assertEqual(row["amount"], 1234567800.0)
        self.assertEqual(row["total_mv"], 2100000000000.0)
        self.assertEqual(row["circ_mv"], 2000000000000.0)

    def test_empty_codes_returns_stable_schema_without_network(self):
        opener = Mock()
        client = TencentQuoteClient(opener=opener)

        result = client.fetch_quotes([])

        opener.assert_not_called()
        self.assertTrue(result.empty)
        self.assertStableColumns(result)

    def test_multi_code_url_preserves_order_and_market_prefixes(self):
        opener = Mock(return_value=b"")
        client = TencentQuoteClient(opener=opener)

        client.fetch_quotes(["600519", "000001.SZ", "bj430047"])

        opener.assert_called_once_with(
            "https://qt.gtimg.cn/q=sh600519,sz000001,bj430047"
        )

    def test_malformed_and_short_lines_are_skipped_with_stable_schema(self):
        raw = (
            'not a quote;'
            'v_sh600519="1~too~short";'
            'v_sz000001=missing_quotes;'
        ).encode("gbk")
        opener = Mock(return_value=raw)
        client = TencentQuoteClient(opener=opener)

        result = client.fetch_quotes(["600519", "000001"])

        self.assertTrue(result.empty)
        self.assertStableColumns(result)

    def test_parse_pe_static_when_index_52_is_present(self):
        values = ["0"] * 53
        values[1] = "平安银行"
        values[2] = "000001"
        values[3] = "12.34"
        values[52] = "11.20"
        raw = f'v_sz000001="{"~".join(values)}";'.encode("gbk")
        opener = Mock(return_value=raw)
        client = TencentQuoteClient(opener=opener)

        result = client.fetch_quotes(["000001"])

        self.assertStableColumns(result)
        row = result.iloc[0]
        self.assertEqual(row["ts_code"], "000001.SZ")
        self.assertEqual(row["pe_static"], 11.20)


class BaiduKlineClientTest(unittest.TestCase):
    def test_parse_kline_accepts_string_result_code_and_ma_fields(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {
            "ResultCode": "0",
            "Result": {
                "newMarketData": {
                    "keys": [
                        "time", "open", "close", "high", "low",
                        "volume", "amount", "ma5avgprice",
                        "ma10avgprice", "ma20avgprice",
                    ],
                    "marketData": (
                        "20260615,11.20,11.10,11.30,11.00,1000,111000,10.9,10.8,10.7;"
                        "20260616,11.10,10.94,11.12,10.91,1200,131280,11.0,10.9,10.8"
                    ),
                }
            },
        }
        session.get.return_value = response
        client = BaiduKlineClient(session=session)

        result = client.fetch_kline_with_ma("000001", start_time="")

        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[0]["ts_code"], "000001.SZ")
        self.assertEqual(result.iloc[1]["close"], 10.94)
        self.assertEqual(result.iloc[1]["ma20"], 10.8)
        self.assertEqual(result.iloc[1]["source"], "baidu")

    def test_parse_kline_accepts_integer_result_code(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {
            "ResultCode": 0,
            "Result": {
                "newMarketData": {
                    "keys": ["time", "open", "close", "high", "low", "volume", "amount"],
                    "marketData": "20260616,11.10,10.94,11.12,10.91,1200,131280",
                }
            },
        }
        session.get.return_value = response
        client = BaiduKlineClient(session=session)

        result = client.fetch_kline_with_ma("000001")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["amount"], 131280.0)


if __name__ == "__main__":
    unittest.main()
