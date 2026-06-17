import datetime
import json
import os
import unittest
from unittest.mock import patch, Mock

import pandas as pd

from core.data_fetcher import DataFetcher, build_stock_code_set, parse_date


class DataFetcherHelpersTest(unittest.TestCase):
    def test_parse_date_accepts_date_object(self):
        self.assertEqual(
            parse_date(datetime.date(2026, 6, 15)),
            "20260615",
        )

    def test_stock_pool_filters_st_names(self):
        stocks = pd.DataFrame({
            "ts_code": ["000001.SZ", "000002.SZ", "600000.SH"],
            "name": ["平安银行", "*ST测试", "浦发银行"],
            "list_status": ["L", "L", "L"],
            "list_date": [None, None, None],
        })
        config = {
            "stock_pool": {
                "include_exchanges": ["SZSE", "SSE"],
                "exclude_st": {"enabled": True},
                "exclude_ipo_within_days": 60,
            }
        }

        result = build_stock_code_set(None, config, stock_df=stocks)

        self.assertEqual(result, ["000001.SZ", "600000.SH"])

    def test_bse_920_codes_are_excluded_by_default_config(self):
        stocks = pd.DataFrame({
            "ts_code": ["920000.BJ", "000001.SZ", "600000.SH"],
            "name": ["安徽凤凰", "平安银行", "浦发银行"],
            "list_status": ["L", "L", "L"],
            "list_date": [None, None, None],
        })
        config = {
            "stock_pool": {
                "include_exchanges": ["SZSE", "SSE"],
                "exclude_st": {"enabled": True},
                "exclude_ipo_within_days": 60,
            }
        }

        result = build_stock_code_set(None, config, stock_df=stocks)

        self.assertEqual(result, ["000001.SZ", "600000.SH"])

    def test_stock_list_marks_920_codes_as_bse(self):
        class FakeAk:
            @staticmethod
            def stock_info_a_code_name():
                return pd.DataFrame({
                    "code": ["920000", "000001", "600000"],
                    "name": ["安徽凤凰", "平安银行", "浦发银行"],
                })

        fetcher = DataFetcher.__new__(DataFetcher)
        fetcher._ak = FakeAk()
        fetcher._rate_limit = lambda: None

        result = fetcher._fetch_stock_list_akshare()

        self.assertEqual(
            result[["symbol", "ts_code", "exchange"]].values.tolist(),
            [
                ["920000", "920000.BJ", "BSE"],
                ["000001", "000001.SZ", "SZSE"],
                ["600000", "600000.SH", "SSE"],
            ],
        )

    def test_tushare_stock_list_preserves_delisted_metadata(self):
        class FakePro:
            def stock_basic(self, exchange, list_status, fields):
                if list_status == "L":
                    return pd.DataFrame({
                        "ts_code": ["000001.SZ"],
                        "symbol": ["000001"],
                        "name": ["平安银行"],
                        "area": ["深圳"],
                        "industry": ["银行"],
                        "list_date": ["19910403"],
                        "delist_date": [None],
                        "market": ["主板"],
                        "exchange": ["SZSE"],
                    })
                return pd.DataFrame({
                    "ts_code": ["000003.SZ"],
                    "symbol": ["000003"],
                    "name": ["PT金田A"],
                    "area": ["深圳"],
                    "industry": ["综合"],
                    "list_date": ["19910703"],
                    "delist_date": ["20020614"],
                    "market": ["主板"],
                    "exchange": ["SZSE"],
                })

        fetcher = DataFetcher.__new__(DataFetcher)
        fetcher._tushare_pro = FakePro()
        fetcher._rate_limit = lambda: None

        result = fetcher._fetch_stock_list_tushare()

        self.assertEqual(
            result[["ts_code", "list_status"]].values.tolist(),
            [["000001.SZ", "L"], ["000003.SZ", "D"]],
        )
        self.assertEqual(
            str(result.loc[result["ts_code"] == "000003.SZ", "delist_date"].iloc[0].date()),
            "2002-06-14",
        )

    def test_tushare_daily_amount_is_normalized_to_yuan(self):
        class FakePro:
            def daily(self, ts_code, start_date, end_date):
                return pd.DataFrame({
                    "ts_code": [ts_code],
                    "trade_date": ["20260616"],
                    "open": [10.0],
                    "high": [11.0],
                    "low": [9.5],
                    "close": [10.5],
                    "vol": [100.0],
                    "amount": [12.3],
                })

        fetcher = DataFetcher.__new__(DataFetcher)
        fetcher._tushare_pro = FakePro()
        fetcher._rate_limit = lambda: None

        result = fetcher._fetch_kline_tushare("000001.SZ", "20260615", "20260616")

        self.assertEqual(result.iloc[0]["amount"], 12300.0)

    def test_long_raw_history_prefers_akshare_before_tencent(self):
        calls = []

        fetcher = DataFetcher.__new__(DataFetcher)
        fetcher._ak = object()
        fetcher._rate_limit = lambda: None

        def fake_ak(symbol, start, end, adjust):
            calls.append(("ak", symbol, start, end, adjust))
            return pd.DataFrame({"trade_date": pd.to_datetime(["2018-01-02"])})

        def fake_tencent(symbol, start, end, adjust):
            calls.append(("tencent", symbol, start, end, adjust))
            return pd.DataFrame()

        fetcher._fetch_kline_akshare_hist = fake_ak
        fetcher._fetch_kline_tencent = fake_tencent

        result = fetcher._fetch_kline_akshare("000001", "20100101", "20260616", "none")

        self.assertFalse(result.empty)
        self.assertEqual(calls[0][0], "ak")

    def test_primary_tushare_prefers_tushare_for_daily_kline(self):
        calls = []
        fetcher = DataFetcher.__new__(DataFetcher)
        fetcher.config = {"data_source": {"primary": "tushare"}}
        fetcher._ak = object()
        fetcher._tushare_pro = object()

        def fake_tushare(ts_code, start, end):
            calls.append(("tushare", ts_code, start, end))
            return pd.DataFrame({
                "ts_code": [ts_code],
                "trade_date": pd.to_datetime(["2026-06-16"]),
                "open": [10.0],
                "high": [11.0],
                "low": [9.5],
                "close": [10.5],
                "vol": [1000.0],
                "amount": [10500.0],
            })

        def fake_akshare(symbol, start, end, adjust):
            calls.append(("akshare", symbol, start, end, adjust))
            return pd.DataFrame()

        fetcher._fetch_kline_tushare = fake_tushare
        fetcher._fetch_kline_akshare = fake_akshare

        result = fetcher.fetch_daily_kline(
            "000001.SZ", "20260615", "20260616", adjust="none"
        )

        self.assertFalse(result.empty)
        self.assertEqual(calls, [("tushare", "000001.SZ", "20260615", "20260616")])

    def test_primary_eastmoney_prefers_eastmoney_for_daily_kline(self):
        calls = []
        fetcher = DataFetcher.__new__(DataFetcher)
        fetcher.config = {"data_source": {"primary": "eastmoney"}}
        fetcher._ak = object()
        fetcher._tushare_pro = None

        def fake_eastmoney(symbol, start, end, adjust):
            calls.append(("eastmoney", symbol, start, end, adjust))
            return pd.DataFrame({
                "ts_code": [f"{symbol}.SZ"],
                "trade_date": pd.to_datetime(["2026-06-16"]),
                "open": [10.0],
                "high": [11.0],
                "low": [9.5],
                "close": [10.5],
                "vol": [1000.0],
                "amount": [10500.0],
            })

        def fake_akshare(symbol, start, end, adjust):
            calls.append(("akshare", symbol, start, end, adjust))
            return pd.DataFrame()

        fetcher._fetch_kline_eastmoney = fake_eastmoney
        fetcher._fetch_kline_akshare = fake_akshare

        result = fetcher.fetch_daily_kline(
            "000001.SZ", "20260615", "20260616", adjust="none"
        )

        self.assertFalse(result.empty)
        self.assertEqual(calls, [("eastmoney", "000001", "20260615", "20260616", "none")])

    def test_tushare_name_history_marks_st_periods(self):
        class FakePro:
            def namechange(self, ts_code, fields):
                return pd.DataFrame({
                    "ts_code": ["000001.SZ", "000001.SZ"],
                    "name": ["平安银行", "*ST平安"],
                    "start_date": ["20200101", "20210101"],
                    "end_date": ["20201231", "20211231"],
                    "change_reason": ["改名", "ST"],
                })

        fetcher = DataFetcher.__new__(DataFetcher)
        fetcher._tushare_pro = FakePro()
        fetcher._rate_limit = lambda: None

        result = fetcher.fetch_stock_name_history("000001.SZ")

        self.assertEqual(result["is_st"].tolist(), [False, True])
        self.assertEqual(
            str(result.iloc[1]["start_date"].date()),
            "2021-01-01",
        )

    def test_compare_market_sources_reports_close_difference(self):
        fetcher = DataFetcher.__new__(DataFetcher)

        def fake_tencent(symbol, start, end, adjust):
            return pd.DataFrame({
                "trade_date": pd.to_datetime(["2026-06-15", "2026-06-16"]),
                "close": [10.0, 11.0],
            })

        def fake_sina(symbol, start, end):
            return pd.DataFrame({
                "trade_date": pd.to_datetime(["2026-06-15", "2026-06-16"]),
                "close": [10.0, 11.22],
            })

        fetcher._fetch_kline_tencent = fake_tencent
        fetcher._fetch_kline_sina = fake_sina

        result = fetcher.compare_market_sources(
            "000001.SZ", "20260615", "20260616", tolerance_pct=1.0
        )

        self.assertEqual(result["secondary_source"], "sina")
        self.assertEqual(result["status"], "warning")
        self.assertEqual(result["compared_rows"], 2)
        self.assertAlmostEqual(result["max_close_diff_pct"], 2.0)

    def test_sina_kline_parses_daily_rows(self):
        payload = (
            '[{"day":"2026-06-15","open":"11.210","high":"11.210",'
            '"low":"10.980","close":"11.060","volume":"154130495"},'
            '{"day":"2026-06-16","open":"11.050","high":"11.120",'
            '"low":"10.910","close":"10.940","volume":"94270804"}]'
        )
        response = Mock(status_code=200, text=payload)
        response.json.return_value = json.loads(payload)
        fetcher = DataFetcher.__new__(DataFetcher)

        with patch("requests.Session.get", return_value=response):
            result = fetcher._fetch_kline_sina("000001", "20260615", "20260616")

        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[0]["ts_code"], "000001.SZ")
        self.assertEqual(result.iloc[0]["close"], 11.06)
        self.assertEqual(result.iloc[0]["vol"], 154130495.0)

    def test_eastmoney_curl_fallback_parses_kline_json(self):
        payload = (
            '{"rc":0,"data":{"klines":['
            '"2026-06-15,11.21,11.06,11.21,10.98,1541305,1711561286.57,2.05,-1.60,-0.18,0.79",'
            '"2026-06-16,11.05,10.94,11.12,10.91,942708,1034554249.38,1.90,-1.08,-0.12,0.49"'
            ']}}'
        )
        completed = Mock(returncode=0, stdout=payload, stderr="")
        fetcher = DataFetcher.__new__(DataFetcher)

        with patch("subprocess.run", return_value=completed) as run:
            result = fetcher._fetch_kline_eastmoney_curl(
                "000001", "20260615", "20260616", "none"
            )

        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[0]["ts_code"], "000001.SZ")
        self.assertEqual(result.iloc[0]["close"], 11.06)
        self.assertEqual(result.iloc[0]["amount"], 1711561286.57)
        self.assertIn("-4", run.call_args.args[0])
        self.assertIn("--noproxy", run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs["env"]["NO_PROXY"], "*")
        self.assertEqual(run.call_args.kwargs["env"]["no_proxy"], "*")

    def test_akshare_eastmoney_call_temporarily_bypasses_system_proxy(self):
        class FakeAk:
            def stock_zh_a_hist(self, **kwargs):
                self.no_proxy = os.environ.get("NO_PROXY")
                self.no_proxy_lower = os.environ.get("no_proxy")
                return pd.DataFrame({
                    "日期": ["2026-06-16"],
                    "开盘": [11.05],
                    "收盘": [10.94],
                    "最高": [11.12],
                    "最低": [10.91],
                    "成交量": [942708],
                    "成交额": [1034554249.38],
                    "涨跌幅": [-1.08],
                })

        fake_ak = FakeAk()
        fetcher = DataFetcher.__new__(DataFetcher)
        fetcher._ak = fake_ak
        fetcher._rate_limit = lambda: None

        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:7897"}, clear=False):
            result = fetcher._fetch_kline_akshare_hist(
                "000001", "20260616", "20260616", "none"
            )

        self.assertEqual(fake_ak.no_proxy, "*")
        self.assertEqual(fake_ak.no_proxy_lower, "*")
        self.assertFalse(result.empty)


if __name__ == "__main__":
    unittest.main()
