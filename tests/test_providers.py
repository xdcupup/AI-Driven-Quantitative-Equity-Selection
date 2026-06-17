import time
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from core.providers.base import ProviderResult, normalize_symbol
from core.providers.eastmoney import EastMoneyClient
from core.providers.rate_limit import EastMoneyLimiter
from core.providers.sina import SinaKlineClient
from core.providers.tencent import TencentKlineClient
from core.providers.tushare import TushareClient


class ProviderBaseTest(unittest.TestCase):
    def test_normalize_symbol_accepts_common_stock_code_formats(self):
        self.assertEqual(normalize_symbol("000001.SZ").symbol, "000001")
        self.assertEqual(normalize_symbol("SZ000001").exchange_suffix, "SZ")
        self.assertEqual(normalize_symbol("sh600000").exchange_suffix, "SH")
        self.assertEqual(normalize_symbol("BJ832000").eastmoney_market, "0")

    def test_provider_result_tracks_source_and_error(self):
        result = ProviderResult(source="eastmoney", ok=False, error="empty")

        self.assertFalse(result.ok)
        self.assertEqual(result.source, "eastmoney")
        self.assertEqual(result.error, "empty")


class EastMoneyProviderTest(unittest.TestCase):
    def test_limiter_sleeps_when_called_too_quickly(self):
        limiter = EastMoneyLimiter(min_interval_sec=1.0, jitter_range=(0.0, 0.0))
        limiter._last_call = 100.0

        with patch("core.providers.rate_limit.time.time", return_value=100.2), \
             patch("core.providers.rate_limit.time.sleep") as sleep:
            limiter.wait()

        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], 0.8)

    def test_client_builds_kline_url_and_uses_limiter(self):
        session = Mock()
        response = Mock(status_code=200, text="{}")
        session.get.return_value = response
        limiter = Mock()
        client = EastMoneyClient(session=session, limiter=limiter)

        got = client.get_kline("000001", "20260615", "20260616", adjust="none")

        self.assertIs(got, response)
        limiter.wait.assert_called_once()
        args, kwargs = session.get.call_args
        self.assertIn("push2his.eastmoney.com", args[0])
        self.assertEqual(kwargs["params"]["secid"], "0.000001")
        self.assertEqual(kwargs["params"]["fqt"], "0")
        self.assertIn("User-Agent", kwargs["headers"])
        self.assertEqual(kwargs["timeout"], 20)


class TencentProviderTest(unittest.TestCase):
    def test_tencent_daily_kline_parses_rows_and_preserves_unknown_amount(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {
            "code": 0,
            "data": {
                "sz000001": {
                    "day": [
                        ["2026-06-14", "11.20", "11.10", "11.30", "11.00", "100"],
                        ["2026-06-15", "11.21", "11.06", "11.21", "10.98", "1541305"],
                        ["2026-06-16", "11.05", "10.94", "11.12", "10.91", "942708"],
                    ]
                }
            },
        }
        session.get.return_value = response
        client = TencentKlineClient(session=session)

        result = client.fetch_daily_kline("000001", "20260615", "20260616", "none")

        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[0]["ts_code"], "000001.SZ")
        self.assertEqual(result.iloc[0]["vol"], 154130500.0)
        self.assertTrue(pd.isna(result.iloc[0]["amount"]))
        self.assertEqual(result.iloc[0]["raw_close"], 11.06)
        self.assertEqual(result.iloc[1]["price_type"], "none")
        args, kwargs = session.get.call_args
        self.assertIn("web.ifzq.gtimg.cn", args[0])
        self.assertEqual(kwargs["proxies"], {"http": "", "https": ""})


class SinaProviderTest(unittest.TestCase):
    def test_sina_daily_kline_parses_rows_for_audit(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = [
            {
                "day": "2026-06-15",
                "open": "11.210",
                "high": "11.210",
                "low": "10.980",
                "close": "11.060",
                "volume": "154130495",
            },
            {
                "day": "2026-06-16",
                "open": "11.050",
                "high": "11.120",
                "low": "10.910",
                "close": "10.940",
                "volume": "94270804",
            },
        ]
        session.get.return_value = response
        client = SinaKlineClient(session=session)

        result = client.fetch_daily_kline("000001", "20260615", "20260616")

        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[0]["ts_code"], "000001.SZ")
        self.assertEqual(result.iloc[0]["close"], 11.06)
        self.assertEqual(result.iloc[0]["vol"], 154130495.0)
        self.assertTrue(pd.isna(result.iloc[0]["amount"]))
        args, kwargs = session.get.call_args
        self.assertIn("quotes.sina.cn", args[0])
        self.assertEqual(kwargs["params"]["symbol"], "sz000001")


class TushareProviderTest(unittest.TestCase):
    def test_stock_list_combines_listed_and_delisted_with_dates(self):
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

        client = TushareClient(FakePro(), rate_limit=lambda: None)

        result = client.fetch_stock_list()

        self.assertEqual(
            result[["ts_code", "list_status"]].values.tolist(),
            [["000001.SZ", "L"], ["000003.SZ", "D"]],
        )
        self.assertEqual(
            str(result.loc[result["ts_code"] == "000003.SZ", "delist_date"].iloc[0].date()),
            "2002-06-14",
        )

    def test_daily_kline_normalizes_amount_to_yuan_and_sorts_dates(self):
        class FakePro:
            def daily(self, ts_code, start_date, end_date):
                return pd.DataFrame({
                    "ts_code": [ts_code, ts_code],
                    "trade_date": ["20260616", "20260615"],
                    "open": [10.0, 9.0],
                    "high": [11.0, 10.0],
                    "low": [9.5, 8.5],
                    "close": [10.5, 9.5],
                    "vol": [100.0, 90.0],
                    "amount": [12.3, 9.8],
                })

        client = TushareClient(FakePro(), rate_limit=lambda: None)

        result = client.fetch_daily_kline("000001.SZ", "20260615", "20260616")

        self.assertEqual(
            result["trade_date"].dt.strftime("%Y%m%d").tolist(),
            ["20260615", "20260616"],
        )
        self.assertEqual(result.iloc[1]["amount"], 12300.0)

    def test_financial_indicators_sort_by_ann_date_and_rename_debt_ratio(self):
        class FakePro:
            def fina_indicator(self, ts_code, start_date, end_date, fields):
                return pd.DataFrame({
                    "ts_code": [ts_code, ts_code],
                    "ann_date": ["20260430", "20260331"],
                    "end_date": ["20260331", "20251231"],
                    "eps": [0.2, 0.8],
                    "dt_debt_to_assets": [41.2, 39.8],
                })

        client = TushareClient(FakePro(), rate_limit=lambda: None)

        result = client.fetch_financial_indicators(
            "000001.SZ", "20260101", "20260616"
        )

        self.assertEqual(
            result["ann_date"].dt.strftime("%Y%m%d").tolist(),
            ["20260331", "20260430"],
        )
        self.assertIn("dt_debt_ratio", result.columns)
        self.assertNotIn("dt_debt_to_assets", result.columns)


if __name__ == "__main__":
    unittest.main()
