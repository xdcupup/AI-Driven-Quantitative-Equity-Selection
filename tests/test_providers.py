import time
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from core.providers.base import ProviderResult, normalize_symbol
from core.providers.eastmoney import EastMoneyClient
from core.providers.rate_limit import EastMoneyLimiter
from core.providers.sina import SinaKlineClient
from core.providers.tencent import TencentKlineClient


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


if __name__ == "__main__":
    unittest.main()
