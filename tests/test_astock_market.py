import unittest
from unittest.mock import Mock

import pandas as pd

from core.astock.market.tencent_quote import TencentQuoteClient
from core.astock.market.baidu_kline import BaiduKlineClient
from core.astock.market.mootdx_client import MootdxMarketClient
from core.astock.market.trade_calendar import TencentTradeCalendarClient
from core.astock.market.stock_list import MootdxStockListClient


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
    EXPECTED_COLUMNS = [
        "ts_code",
        "trade_date",
        "open",
        "close",
        "high",
        "low",
        "vol",
        "amount",
        "ma5",
        "ma10",
        "ma20",
        "source",
    ]

    def assertStableColumns(self, result):
        self.assertEqual(list(result.columns), self.EXPECTED_COLUMNS)

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
        self.assertStableColumns(result)

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
        self.assertStableColumns(result)

    def test_nonzero_result_code_returns_stable_empty_schema(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {"ResultCode": 1}
        session.get.return_value = response
        client = BaiduKlineClient(session=session)

        result = client.fetch_kline_with_ma("000001")

        self.assertTrue(result.empty)
        self.assertStableColumns(result)

    def test_json_decode_failure_returns_stable_empty_schema(self):
        session = Mock()
        response = Mock()
        response.json.side_effect = ValueError("bad json")
        session.get.return_value = response
        client = BaiduKlineClient(session=session)

        result = client.fetch_kline_with_ma("000001")

        self.assertTrue(result.empty)
        self.assertStableColumns(result)

    def test_top_level_non_dict_payload_returns_stable_empty_schema(self):
        for payload in [None, [], "bad"]:
            with self.subTest(payload=payload):
                session = Mock()
                response = Mock()
                response.json.return_value = payload
                session.get.return_value = response
                client = BaiduKlineClient(session=session)

                result = client.fetch_kline_with_ma("000001")

                self.assertTrue(result.empty)
                self.assertStableColumns(result)

    def test_missing_or_none_payload_pieces_return_stable_empty_schema(self):
        payloads = [
            {"ResultCode": 0},
            {"ResultCode": 0, "Result": None},
            {"ResultCode": 0, "Result": {"newMarketData": None}},
            {"ResultCode": 0, "Result": {"newMarketData": {"marketData": ""}}},
            {
                "ResultCode": 0,
                "Result": {"newMarketData": {"keys": None, "marketData": "20260616"}},
            },
            {
                "ResultCode": 0,
                "Result": {"newMarketData": {"keys": ["time"], "marketData": None}},
            },
            {
                "ResultCode": 0,
                "Result": {"newMarketData": {"keys": ["time"], "marketData": ["20260616"]}},
            },
        ]

        for payload in payloads:
            with self.subTest(payload=payload):
                session = Mock()
                response = Mock()
                response.json.return_value = payload
                session.get.return_value = response
                client = BaiduKlineClient(session=session)

                result = client.fetch_kline_with_ma("000001")

                self.assertTrue(result.empty)
                self.assertStableColumns(result)

    def test_malformed_and_short_rows_are_skipped_with_stable_schema(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {
            "ResultCode": 0,
            "Result": {
                "newMarketData": {
                    "keys": [
                        "time", "open", "close", "high", "low",
                        "volume", "amount", "ma5avgprice",
                        "ma10avgprice", "ma20avgprice",
                    ],
                    "marketData": (
                        "not-a-row;"
                        "20260616,11.10;"
                        "20260617,11.10,10.94,11.12,10.91,1200,131280,11.0,10.9,10.8"
                    ),
                }
            },
        }
        session.get.return_value = response
        client = BaiduKlineClient(session=session)

        result = client.fetch_kline_with_ma("000001")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["trade_date"], pd.Timestamp("2026-06-17"))
        self.assertEqual(result.iloc[0]["close"], 10.94)
        self.assertStableColumns(result)

    def test_invalid_or_missing_dates_are_dropped(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {
            "ResultCode": 0,
            "Result": {
                "newMarketData": {
                    "keys": ["time", "open", "close", "high", "low", "volume", "amount"],
                    "marketData": (
                        "bad-date,11.10,10.94,11.12,10.91,1200,131280;"
                        ",11.10,10.94,11.12,10.91,1200,131280;"
                        "20260618,11.20,11.00,11.30,10.98,1500,165000"
                    ),
                }
            },
        }
        session.get.return_value = response
        client = BaiduKlineClient(session=session)

        result = client.fetch_kline_with_ma("000001")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["trade_date"], pd.Timestamp("2026-06-18"))
        self.assertEqual(result.iloc[0]["amount"], 165000.0)
        self.assertStableColumns(result)


class MootdxMarketClientTest(unittest.TestCase):
    EXPECTED_COLUMNS = [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
        "source",
    ]

    def assertStableColumns(self, result):
        self.assertEqual(list(result.columns), self.EXPECTED_COLUMNS)

    def test_daily_kline_normalizes_fake_client_rows(self):
        class FakeQuotes:
            def bars(self, symbol, market, category, offset):
                self.call = (symbol, market, category, offset)
                return pd.DataFrame({
                    "datetime": ["2026-06-15", "2026-06-16"],
                    "open": [11.2, 11.1],
                    "close": [11.1, 10.94],
                    "high": [11.3, 11.12],
                    "low": [11.0, 10.91],
                    "vol": [1000.0, 1200.0],
                    "amount": [111000.0, 131280.0],
                })

        fake = FakeQuotes()
        client = MootdxMarketClient(quotes=fake)

        result = client.fetch_daily_kline("000001.SZ", "20260615", "20260616")

        self.assertEqual(fake.call, ("000001", 0, 4, 1200))
        self.assertEqual(result.iloc[0]["ts_code"], "000001.SZ")
        self.assertEqual(result.iloc[1]["close"], 10.94)
        self.assertEqual(result.iloc[1]["source"], "mootdx")
        self.assertStableColumns(result)

    def test_daily_kline_skips_bse_in_stage_one(self):
        client = MootdxMarketClient(quotes=Mock())

        result = client.fetch_daily_kline("832000.BJ", "20260615", "20260616")

        self.assertTrue(result.empty)
        self.assertStableColumns(result)

    def test_daily_kline_empty_or_none_response_uses_stable_schema(self):
        class FakeQuotes:
            def __init__(self, payload):
                self.payload = payload

            def bars(self, symbol, market, category, offset):
                return self.payload

        for payload in (None, pd.DataFrame()):
            with self.subTest(payload=payload):
                client = MootdxMarketClient(quotes=FakeQuotes(payload))

                result = client.fetch_daily_kline("000001.SZ", "20260615", "20260616")

                self.assertTrue(result.empty)
                self.assertStableColumns(result)

    def test_daily_kline_drops_invalid_dates(self):
        class FakeQuotes:
            def bars(self, symbol, market, category, offset):
                return pd.DataFrame({
                    "datetime": ["bad-date", "2026-06-16"],
                    "open": [11.2, 11.1],
                    "close": [11.1, 10.94],
                    "high": [11.3, 11.12],
                    "low": [11.0, 10.91],
                    "vol": [1000.0, 1200.0],
                    "amount": [111000.0, 131280.0],
                })

        client = MootdxMarketClient(quotes=FakeQuotes())

        result = client.fetch_daily_kline("000001.SZ", "20260615", "20260616")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["trade_date"], pd.Timestamp("2026-06-16"))
        self.assertStableColumns(result)


class TencentTradeCalendarClientTest(unittest.TestCase):
    EXPECTED_COLUMNS = [
        "exchange",
        "trade_date",
        "is_open",
        "pretrade_date",
        "source",
    ]

    def test_parses_index_kline_dates_as_open_trading_days(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {
            "code": 0,
            "data": {
                "sh000001": {
                    "day": [
                        ["2026-02-13", "1", "1", "1", "1", "1"],
                        ["2026-02-23", "1", "1", "1", "1", "1"],
                        ["2026-02-24", "1", "1", "1", "1", "1"],
                    ]
                }
            },
        }
        session.get.return_value = response
        client = TencentTradeCalendarClient(session=session)

        result = client.fetch_trade_calendar(2026)

        self.assertEqual(list(result.columns), self.EXPECTED_COLUMNS)
        self.assertEqual(
            result["trade_date"].dt.strftime("%Y-%m-%d").tolist(),
            ["2026-02-13", "2026-02-23", "2026-02-24"],
        )
        self.assertEqual(result["is_open"].tolist(), [1, 1, 1])
        self.assertEqual(result.iloc[0]["source"], "tencent_index_kline")
        self.assertTrue(pd.isna(result.iloc[0]["pretrade_date"]))
        self.assertEqual(result.iloc[1]["pretrade_date"], pd.Timestamp("2026-02-13"))

    def test_bad_response_returns_business_day_fallback(self):
        session = Mock()
        response = Mock(status_code=500)
        session.get.return_value = response
        client = TencentTradeCalendarClient(session=session)

        result = client.fetch_trade_calendar(2026)

        self.assertEqual(list(result.columns), self.EXPECTED_COLUMNS)
        self.assertFalse(result.empty)
        self.assertEqual(result.iloc[0]["source"], "business_day_fallback")
        self.assertTrue((result["trade_date"].dt.year == 2026).all())
        self.assertEqual(result["is_open"].unique().tolist(), [1])


class MootdxStockListClientTest(unittest.TestCase):
    EXPECTED_COLUMNS = [
        "ts_code",
        "symbol",
        "name",
        "exchange",
        "area",
        "industry",
        "list_status",
        "list_date",
        "delist_date",
        "source",
    ]

    def test_fetch_stock_list_normalizes_and_filters_a_shares(self):
        class FakeQuotes:
            def stocks(self, market):
                if market == 0:
                    return pd.DataFrame({
                        "code": ["000001", "002594", "000015", "000022", "159915", "200001"],
                        "name": ["平安银行", "比亚迪\x00", "红利指数", "沪公司债", "创业板ETF", "深物业B"],
                    })
                return pd.DataFrame({
                    "code": ["600519", "688001", "510300", "900901"],
                    "name": ["贵州茅台", "华兴源创", "沪深300ETF", "云赛B股"],
                })

        client = MootdxStockListClient(quotes=FakeQuotes())

        result = client.fetch_stock_list()

        self.assertEqual(list(result.columns), self.EXPECTED_COLUMNS)
        self.assertEqual(
            result[["ts_code", "name", "exchange"]].values.tolist(),
            [
                ["000001.SZ", "平安银行", "SZ"],
                ["002594.SZ", "比亚迪", "SZ"],
                ["600519.SH", "贵州茅台", "SH"],
                ["688001.SH", "华兴源创", "SH"],
            ],
        )
        self.assertEqual(result["list_status"].unique().tolist(), ["L"])
        self.assertEqual(result["source"].unique().tolist(), ["mootdx"])

    def test_fetch_stock_list_deduplicates_and_returns_stable_empty_on_error(self):
        class DuplicateQuotes:
            def stocks(self, market):
                if market == 0:
                    return pd.DataFrame({"code": ["000001"], "name": ["平安银行"]})
                return pd.DataFrame({"code": ["000001"], "name": ["重复平安"]})

        result = MootdxStockListClient(quotes=DuplicateQuotes()).fetch_stock_list()

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["ts_code"], "000001.SZ")

        class BrokenQuotes:
            def stocks(self, market):
                raise RuntimeError("network down")

        empty = MootdxStockListClient(quotes=BrokenQuotes()).fetch_stock_list()

        self.assertTrue(empty.empty)
        self.assertEqual(list(empty.columns), self.EXPECTED_COLUMNS)


if __name__ == "__main__":
    unittest.main()
